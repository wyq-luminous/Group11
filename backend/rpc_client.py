"""
rpc_client.py — msgpack-RPC client for arduino-router Unix socket.

Connects to /var/run/arduino-router.sock, sends msgpack-RPC requests,
and returns the first complete response message.

CRITICAL: Uses msgpack.Unpacker for streaming — reads until the first
complete msgpack object is received, then returns immediately. Do NOT
"read until EOF" or the call will block forever and discard the response.

Protocol:
  Request:  [type, msgid, method, params]
  Response: [type, msgid, error, result]

  type=0: request, type=1: response
  error=null on success, error=[code, message] on failure
"""

import msgpack
import socket


class RpcError(Exception):
    """Raised when the RPC server returns an error."""

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"RPC error [{code}]: {message}")


class RpcClient:
    """Streaming msgpack-RPC client for arduino-router."""

    def __init__(self, socket_path="/var/run/arduino-router.sock", timeout=5.0):
        self.socket_path = socket_path
        self.timeout = timeout
        self._msgid = 0

    def _next_msgid(self):
        self._msgid += 1
        return self._msgid

    def _connect(self):
        """Create a new Unix socket connection."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        return sock

    def call(self, method, *params):
        """
        Make an RPC call and return the result.

        Reads raw bytes from the socket and unpacks the first complete
        msgpack message. Does NOT use makefile() because its buffered
        reader blocks waiting for more data when the socket stays open.

        Args:
            method: RPC method name (e.g. "$/version", "matrix.scroll_text")
            *params: Method parameters

        Returns:
            The result value from the RPC response.

        Raises:
            RpcError: If the RPC server returns an error.
            OSError: If socket connection/read fails.
            TimeoutError: If the call times out.
        """
        msgid = self._next_msgid()
        request = [0, msgid, method, list(params)]

        sock = self._connect()
        try:
            # Send request
            packed = msgpack.packb(request)
            sock.sendall(packed)

            # Read response in chunks until we have at least one complete
            # msgpack message, then unpack and return immediately.
            buf = bytearray()
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        raise RpcError(-1, "Connection closed by peer")
                    buf.extend(chunk)
                except TimeoutError:
                    raise RpcError(-1, f"RPC call timed out: {method}")

                # Try to unpack; if incomplete, keep reading
                try:
                    response = msgpack.unpackb(bytes(buf), raw=False)
                    return self._parse_response(response, msgid)
                except ValueError as e:
                    msg = str(e).lower()
                    if "incomplete" in msg or "exceeds" in msg:
                        continue  # need more data
                    raise  # real error
        finally:
            sock.close()

    def _parse_response(self, response, expected_msgid):
        """Validate and extract result from an RPC response."""
        if not isinstance(response, list) or len(response) < 4:
            raise RpcError(-1, f"Malformed response: {response}")

        resp_type, resp_msgid, error, result = (
            response[0], response[1], response[2], response[3]
        )

        if resp_msgid != expected_msgid:
            raise RpcError(
                -1, f"Message id mismatch: expected {expected_msgid}, got {resp_msgid}"
            )

        if error is not None:
            if isinstance(error, list) and len(error) >= 2:
                raise RpcError(error[0], error[1])
            raise RpcError(-1, str(error))

        return result


# ---------------------------------------------------------------------------
# Convenience: shared client instance (lazy, one per call)
# ---------------------------------------------------------------------------
_default_socket = "/var/run/arduino-router.sock"


def rpc_call(method, *params, socket_path=None, timeout=5.0):
    """Convenience function: single RPC call."""
    path = socket_path or _default_socket
    client = RpcClient(path, timeout)
    return client.call(method, *params)


# ---------------------------------------------------------------------------
# Self-test (run with: python3 -m backend.rpc_client)
# ---------------------------------------------------------------------------
def self_test(socket_path=None):
    """Run a self-test suite against the RPC router. Returns True if ok."""
    path = socket_path or _default_socket
    passed = 0
    failed = 0

    def check(name, fn):
        nonlocal passed, failed
        try:
            result = fn()
            print(f"  OK  {name}: {result}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {name}: {e}")
            failed += 1

    print(f"RPC Self-Test — {path}")
    print()

    client = RpcClient(path, timeout=5.0)

    # Test 1: version
    check("$/version", lambda: client.call("$/version"))

    # Test 2: mon/connected should be True
    check("mon/connected", lambda: client.call("mon/connected"))

    # Test 3: non-existent method should return error code 2
    try:
        result = client.call("nonexistent.method.12345")
        print(f"  FAIL nonexistent method: should have raised RpcError, got {result}")
        failed += 1
    except RpcError as e:
        if e.code == 2:
            print(f"  OK  nonexistent method: correctly returned [{e.code}, '{e.message}']")
            passed += 1
        else:
            print(f"  FAIL nonexistent method: wrong error code {e.code}: {e.message}")
            failed += 1
    except Exception as e:
        print(f"  FAIL nonexistent method: unexpected exception: {e}")
        failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    import sys
    ok = self_test()
    sys.exit(0 if ok else 1)
