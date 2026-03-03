import socket
import threading
import ssl
import json
import logging

class ClientHTTP:
    def __init__(self, host, port=443, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._context = ssl.create_default_context()
        self._logger = logging.getLogger(__name__)
        self._socket = None
        self._lock = threading.Lock()
        
    def request(self, payload):
        with self._lock:
            body = json.dumps(payload).encode("utf-8")

            request = (
                "POST / HTTP/1.1\r\n"
                f"Host: {self.host}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("utf-8") + body

            sock = socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout
            )

            ssl_sock = self._context.wrap_socket(
                sock,
                server_hostname=self.host
            )

            try:
                self._logger.debug("Sending HTTP Request:\n%s", request.decode())
                ssl_sock.sendall(request)

                response = b""
                while True:
                    chunk = ssl_sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk

            finally:
                ssl_sock.close()

            self._logger.debug("Received HTTP Response:\n%s", response.decode())

            return self._parse_response(response)

    def _parse_response(self, response):
        header_bytes, _, body = response.partition(b"\r\n\r\n")
        headers = header_bytes.decode()

        status_line = headers.split("\r\n")[0]
        parts = status_line.split(" ")
        if len(parts) < 2 or parts[1] != "200":
            raise Exception(f"HTTP error: {status_line}")

        if "transfer-encoding: chunked" in headers.lower():
            body = self._decode_chunked(body)

        self._logger.debug("Parsed body:\n%s", body.decode())

        return json.loads(body.decode())

    @staticmethod
    def _decode_chunked(body):
        decoded = b""
        while body:
            line, _, body = body.partition(b"\r\n")
            size = int(line.decode(), 16)
            if size == 0:
                break
            decoded += body[:size]
            body = body[size + 2:]
        return decoded
