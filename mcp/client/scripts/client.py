__version__ = "1.0.0"
import json
import logging
import queue
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from mcp.security import read_bounded_line, redact_secret_text

logger = logging.getLogger(__name__)

#: Number of restart attempts (with exponential backoff) before a degraded MCP
#: server is declared unavailable.  All reconnects are lazy — there are no
#: background timers poking the transport.
MAX_RECONNECT_ATTEMPTS = 3

#: Handshake/discovery budget. A stdio MCP server that starts but never
#: answers must not stall Nexus startup for the full 30s per-call default:
#: with several configured servers that serialises into minutes of dead
#: wait before the agent loop is usable.
#:
#: These must NOT be tightened aggressively. The shipped catalog uses
#: ``npx -y @modelcontextprotocol/server-*``, which on a cold npm cache
#: downloads the package before it can answer, and Docker-based servers
#: pay container start. 20s keeps a real cold start working while still
#: cutting a hung server's cost by a third; the circuit breaker below is
#: what actually makes repeated calls to a dead server cheap.
MCP_HANDSHAKE_TIMEOUT = 20
MCP_DISCOVERY_TIMEOUT = 20

#: Circuit breaker. Once a server has exhausted its reconnect budget it is
#: ``unavailable``; re-running the full backoff cycle on every subsequent
#: call makes one dead server cost minutes repeatedly. Hold the breaker
#: open for this long, then allow one half-open retry.
MCP_BREAKER_COOLDOWN = 60.0


class MCPClient:
    """
    A simple MCP client for NEXUS to communicate with MCP servers over stdio.
    Handles JSON-RPC request/response lifecycle.

    The client tracks a lifecycle ``state`` (healthy | degraded | unavailable)
    and recovers from transport failures lazily on the next ``call()``: the
    session is marked degraded, the owning registry is asked to park the
    server's tools, and a bounded exponential-backoff reconnect + ``tools/list``
    re-probe attempt is made in-band (no threading timers).
    """

    def __init__(self, command: str, args: List[str]):
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise ValueError("MCP command must be a non-empty executable path or name")
        if not all(isinstance(arg, str) and "\x00" not in arg for arg in args):
            raise ValueError("MCP arguments must be strings without NUL bytes")
        self.command = command
        self.args = list(args)
        self.process: Optional[subprocess.Popen] = None
        self.responses: Dict[str, queue.Queue] = {}
        self.id_counter = 0
        self._lock = threading.Lock()
        # Serializes writes to the child's stdin. Concurrent tool calls run in
        # worker threads; without this, two interleaved write()/flush() pairs
        # corrupt the JSON-RPC message framing for everyone.
        self._stdin_lock = threading.Lock()
        # ``call_tool`` is commonly dispatched through worker threads. Keep
        # process lifecycle transitions single-owner so concurrent first calls
        # cannot launch multiple MCP children for one configured server.
        self._lifecycle_lock = threading.RLock()
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        # Lifecycle state for reconnect/parking.  "unavailable" until the first
        # successful start(); flipped to "degraded" on transport failure and
        # back to "healthy" after a successful re-probe.
        self.state = "unavailable"
        self._reconnecting = False
        #: Monotonic time the breaker opened; 0.0 means closed.
        self._breaker_opened_at = 0.0
        # Optional registry integration hooks (installed by ToolRegistry so a
        # dead server's tools can be parked and later restored).
        self.degraded_cb = None   # callable() -> None  (park tools)
        self.recover_cb = None    # callable(list_of_tool_defs) -> None (restore)

    def is_running(self) -> bool:
        """Return True only when the child process is still alive."""
        return self.process is not None and self.process.poll() is None

    def health_probe(self) -> str:
        """Report current health: ``healthy | degraded | unavailable``."""
        if self.state == "healthy" and not self.is_running():
            # Process died without the recovery cycle noticing; report degraded
            # so the next call triggers a lazy re-probe (and parked tools can be
            # restored) instead of an immediate permanent drop.
            return "degraded"
        return self.state

    def _clear_exited_process(self) -> None:
        if self.process is not None and self.process.poll() is not None:
            logger.warning("MCP server process exited with code %s", self.process.returncode)
            self._running = False
            self.process = None
        elif self.process is None:
            self._running = False

    def start(self) -> bool:
        """Start the MCP server process."""
        with self._lifecycle_lock:
            return self._start_unlocked()

    def _start_unlocked(self) -> bool:
        if self.is_running():
            return True
        # Respect the breaker here too: without this, every call to a
        # dead server paid a fresh handshake timeout before the recovery
        # cycle could even consult the breaker.
        opened_at = getattr(self, "_breaker_opened_at", 0.0)
        if opened_at and (time.time() - opened_at) < MCP_BREAKER_COOLDOWN:
            return False
        self._clear_exited_process()

        logger.info("Starting MCP server executable: %s", self.command)
        try:
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                # Never reinterpret already-tokenized arguments through a shell.
                shell=False,
            )
        except OSError as exc:
            logger.error("Failed to start MCP server executable %s: %s", self.command, redact_secret_text(str(exc)))
            self.process = None
            self._running = False
            self.state = "unavailable"
            return False

        self._running = True
        self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader_thread.start()

        # Monitor stderr
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()

        # Initialize
        init_result = self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "nexus-ai", "version": "1.0.0"}
        }, timeout=MCP_HANDSHAKE_TIMEOUT)

        # A timed-out or errored handshake returns an ``{"error": ...}``
        # envelope, which is TRUTHY. Treating that as success marked a
        # server that never answered as ``healthy`` and published its
        # tools to the model, so every later call paid a full timeout.
        if init_result and not (isinstance(init_result, dict) and init_result.get("error")):
            self.send_notification("notifications/initialized")
            self.state = "healthy"
            # A completed handshake means the server is genuinely back:
            # close the breaker so recovery is not gated on a stale
            # cooldown from an earlier outage.
            self._breaker_opened_at = 0.0
            logger.info("MCP server initialized")
            return True
        else:
            logger.error("Failed to initialize MCP server")
            self.state = "unavailable"
            self.stop()
            return False

    def stop(self):
        """Stop the MCP server process."""
        with self._lifecycle_lock:
            self._running = False
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                self.process = None
            for thread in (self._reader_thread, self._stderr_thread):
                if thread is not None and thread.is_alive():
                    thread.join(timeout=2)
            self._reader_thread = None
            self._stderr_thread = None

    def _read_stdout(self):
        """Reader loop for stdout."""
        # Capture the process for this generation: after a recovery the old
        # thread must keep draining the OLD pipe (until EOF) and must never
        # read the new process's stdout, or it can steal the new server's
        # responses.
        process = self.process
        reader = process.stdout if process is not None else None
        while self._running and process is self.process and reader is not None:
            line, oversized = read_bounded_line(reader)
            if oversized:
                logger.error("Rejected oversized MCP stdout message")
                continue
            if not line:
                break

            try:
                data = json.loads(line)
                req_id = data.get("id")
                if req_id is not None:
                    req_id = str(req_id)
                    with self._lock:
                        if req_id in self.responses:
                            self.responses[req_id].put(data)
                else:
                    logger.debug(f"Received MCP notification: {data}")
            except json.JSONDecodeError:
                logger.error("Failed to decode MCP message (%d characters)", len(line))

    def _read_stderr(self):
        """Monitor stderr for debug logs."""
        process = self.process
        reader = process.stderr if process is not None else None
        while self._running and process is self.process and reader is not None:
            line, oversized = read_bounded_line(reader)
            if oversized:
                logger.error("Rejected oversized MCP stderr message")
                continue
            if not line:
                break
            logger.debug("MCP Server Debug: %s", redact_secret_text(line.strip()))

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """Make a synchronous JSON-RPC call, recovering lazily from transport failures."""
        return self._round_trip(method, params, timeout)

    def _round_trip(self, method: str, params: Optional[Dict[str, Any]], timeout: int, _recovering: bool = False):
        """Single request/response exchange with lazy reconnect on write failure."""
        if not self.is_running() or not self.process or not self.process.stdin:
            if not self.start():
                if _recovering or self._reconnecting:
                    return None
                if self._recover():
                    return self._round_trip(method, params, timeout, _recovering=True)
                return None

        if not self.is_running() or not self.process or not self.process.stdin:
            return None

        with self._lock:
            self.id_counter += 1
            req_id = str(self.id_counter)
            q = queue.Queue(maxsize=1)
            self.responses[req_id] = q

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        try:
            with self._stdin_lock:
                self.process.stdin.write(json.dumps(request) + "\n")
                self.process.stdin.flush()
        except OSError as e:
            logger.error("Failed to write to MCP server: %s", redact_secret_text(str(e)))
            self.stop()
            with self._lock:
                if req_id in self.responses:
                    del self.responses[req_id]
            if _recovering or self._reconnecting:
                return None
            if self._recover():
                return self._round_trip(method, params, timeout, _recovering=True)
            return None

        try:
            response = q.get(timeout=timeout)
            if "error" in response:
                error_obj = response["error"]
                error_msg = error_obj.get("message", "Unknown MCP error")
                logger.error(f"MCP error in {method}: {error_msg}")
                return {"error": error_msg, "code": error_obj.get("code")}
            return response.get("result")
        except queue.Empty:
            logger.error(f"MCP call timed out: {method}")
            # A server that stops answering is dead-weight: every later call
            # would re-pay the full timeout against the same hung process.
            # Tear it down so the next call starts fresh via start()/recovery.
            self.stop()
            return {"error": f"Timeout calling {method}"}
        finally:
            with self._lock:
                if req_id in self.responses:
                    del self.responses[req_id]

    def _recover(self, max_attempts: int = MAX_RECONNECT_ATTEMPTS) -> bool:
        """Run one serialized bounded recovery cycle."""
        with self._lifecycle_lock:
            return self._recover_unlocked(max_attempts)

    def _recover_unlocked(self, max_attempts: int = MAX_RECONNECT_ATTEMPTS) -> bool:
        """Mark the session degraded, park tools, and reconnect with backoff.

        Returns True when the server is healthy again (restart + successful
        ``tools/list`` re-probe).  Backoff is 1s, 2s, 4s … capped at 60s and
        bounded to ``max_attempts``.  Blocks only the calling thread — never a
        background timer.
        """
        if self._reconnecting:
            return False
        # Breaker open: fail fast instead of replaying the whole backoff
        # cycle against a server already proven dead. One half-open retry
        # is allowed once the cooldown elapses.
        opened_at = getattr(self, "_breaker_opened_at", 0.0)
        if opened_at and (time.time() - opened_at) < MCP_BREAKER_COOLDOWN:
            return False
        self._breaker_opened_at = 0.0
        self._reconnecting = True
        try:
            self.state = "degraded"
            if self.degraded_cb is not None:
                try:
                    self.degraded_cb()
                except Exception:
                    logger.debug("MCP degraded hook failed", exc_info=True)
            delay = 1.0
            for attempt in range(1, max_attempts + 1):
                if self.start():
                    tools = self._probe_tools()
                    if tools is not None:
                        if self.recover_cb is not None:
                            try:
                                self.recover_cb(tools)
                            except Exception:
                                logger.debug("MCP recover hook failed", exc_info=True)
                        self.state = "healthy"
                        logger.info("MCP server '%s' recovered", self.command)
                        return True
                self.stop()
                if attempt < max_attempts:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
            self.state = "unavailable"
            self._breaker_opened_at = time.time()
            logger.warning("MCP server '%s' unavailable after %d reconnect attempts", self.command, max_attempts)
            return False
        finally:
            self._reconnecting = False

    def _probe_tools(self) -> Optional[List[Dict[str, Any]]]:
        """Re-probe the server tool list after a successful restart.

        Returns the list of tool definitions on success, or None when the
        server could not answer ``tools/list`` (probe failed).
        """
        try:
            result = self.call("tools/list", timeout=10)
        except Exception:
            return None
        if isinstance(result, dict) and "error" not in result:
            tools = result.get("tools")
            return tools if isinstance(tools, list) else []
        return None

    def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None):
        """Send a JSON-RPC notification."""
        if not self.process or not self.process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }

        try:
            with self._stdin_lock:
                self.process.stdin.write(json.dumps(notification) + "\n")
                self.process.stdin.flush()
        except OSError as e:
            logger.error(f"Failed to write notification to MCP server: {e}")

    def list_tools(self) -> List[Dict[str, Any]]:
        """List tools available on the MCP server."""
        result = self.call("tools/list", timeout=MCP_DISCOVERY_TIMEOUT)
        if not result or (isinstance(result, dict) and result.get("error")):
            return []
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Call a specific tool on the MCP server."""
        return self.call("tools/call", {"name": name, "arguments": arguments})
