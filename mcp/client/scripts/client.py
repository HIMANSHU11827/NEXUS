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
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        # Lifecycle state for reconnect/parking.  "unavailable" until the first
        # successful start(); flipped to "degraded" on transport failure and
        # back to "healthy" after a successful re-probe.
        self.state = "unavailable"
        self._reconnecting = False
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
        if self.is_running():
            return True
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
        threading.Thread(target=self._read_stderr, daemon=True).start()

        # Initialize
        init_result = self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "nexus-ai", "version": "1.0.0"}
        })

        if init_result:
            self.send_notification("notifications/initialized")
            self.state = "healthy"
            logger.info("MCP server initialized")
            return True
        else:
            logger.error("Failed to initialize MCP server")
            self.state = "unavailable"
            self.stop()
            return False

    def stop(self):
        """Stop the MCP server process."""
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _read_stdout(self):
        """Reader loop for stdout."""
        while self._running and self.process and self.process.stdout:
            line, oversized = read_bounded_line(self.process.stdout)
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
        while self._running and self.process and self.process.stderr:
            line, oversized = read_bounded_line(self.process.stderr)
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
            self._clear_exited_process()
            return {"error": f"Timeout calling {method}"}
        finally:
            with self._lock:
                if req_id in self.responses:
                    del self.responses[req_id]

    def _recover(self, max_attempts: int = MAX_RECONNECT_ATTEMPTS) -> bool:
        """Mark the session degraded, park tools, and reconnect with backoff.

        Returns True when the server is healthy again (restart + successful
        ``tools/list`` re-probe).  Backoff is 1s, 2s, 4s … capped at 60s and
        bounded to ``max_attempts``.  Blocks only the calling thread — never a
        background timer.
        """
        if self._reconnecting:
            return False
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
            self.process.stdin.write(json.dumps(notification) + "\n")
            self.process.stdin.flush()
        except OSError as e:
            logger.error(f"Failed to write notification to MCP server: {e}")

    def list_tools(self) -> List[Dict[str, Any]]:
        """List tools available on the MCP server."""
        result = self.call("tools/list")
        return result.get("tools", []) if result else []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Call a specific tool on the MCP server."""
        return self.call("tools/call", {"name": name, "arguments": arguments})
