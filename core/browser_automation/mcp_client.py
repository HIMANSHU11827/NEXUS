import json
import subprocess
import threading
import queue
import time
import logging
import os
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)

class MCPClient:
    """
    A simple MCP client for NEXUS to communicate with MCP servers over stdio.
    Handles JSON-RPC request/response lifecycle.
    """

    def __init__(self, command: str, args: List[str]):
        self.command = command
        self.args = args
        self.process: Optional[subprocess.Popen] = None
        self.responses: Dict[str, queue.Queue] = {}
        self.id_counter = 0
        self._lock = threading.Lock()
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the MCP server process."""
        if self.process:
            return

        logger.info(f"Starting MCP server: {self.command} {' '.join(self.args)}")
        self.process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            shell=os.name == "nt",
        )

        self._running = True
        self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader_thread.start()
        
        # Monitor stderr
        threading.Thread(target=self._read_stderr, daemon=True).start()
        
        # Initialize
        init_result = self.call("initialize", {
            "protocolVersion": "2024-11-05", # Updated to a recent version
            "capabilities": {},
            "clientInfo": {"name": "nexus-ai", "version": "1.0.0"}
        })
        
        if init_result:
            self.send_notification("notifications/initialized")
            logger.info("MCP server initialized")
        else:
            logger.error("Failed to initialize MCP server")

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
            line = self.process.stdout.readline()
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
                    # Notification or error without ID
                    logger.debug(f"Received MCP notification: {data}")
            except json.JSONDecodeError:
                logger.error(f"Failed to decode MCP message: {line}")

    def _read_stderr(self):
        """Monitor stderr for debug logs."""
        while self._running and self.process and self.process.stderr:
            line = self.process.stderr.readline()
            if not line:
                break
            logger.debug(f"MCP Server Debug: {line.strip()}")

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """Make a synchronous JSON-RPC call."""
        if not self.process or not self.process.stdin:
            self.start()
        
        if not self.process or not self.process.stdin:
            return None

        with self._lock:
            self.id_counter += 1
            req_id = str(self.id_counter)
            q = queue.Queue()
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
            logger.error(f"Failed to write to MCP server: {e}")
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
            return {"error": f"Timeout calling {method}"}
        finally:
            with self._lock:
                if req_id in self.responses:
                    del self.responses[req_id]

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
