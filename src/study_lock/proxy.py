from __future__ import annotations

import select
import socket
import socketserver
from dataclasses import dataclass
from urllib.parse import urlsplit

from .domain_rules import domain_allowed


WEB_PORTS = {80, 443}


def parse_connect_target(target: str) -> tuple[str, int]:
    if target.count(":") != 1:
        raise ValueError("CONNECT target must be host:port")
    host, raw_port = target.rsplit(":", 1)
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("CONNECT port must be an integer") from exc
    if not host or port not in WEB_PORTS:
        raise ValueError("CONNECT target must use port 80 or 443")
    return host, port


@dataclass(frozen=True)
class ProxyPolicy:
    allowed_domains: set[str]

    def allows(self, host: str, port: int) -> bool:
        return port in WEB_PORTS and domain_allowed(host, self.allowed_domains)


class _ProxyHandler(socketserver.StreamRequestHandler):
    server: "AllowlistProxyServer"

    def handle(self) -> None:
        request_line = self.rfile.readline(65536)
        if not request_line:
            return
        parts = request_line.decode("iso-8859-1").strip().split()
        if len(parts) != 3:
            self._send_error(400, "Malformed request")
            return
        method, target, version = parts
        headers = self._read_headers()
        if method.upper() == "CONNECT":
            self._handle_connect(target)
        else:
            self._handle_http(method, target, version, headers)

    def _read_headers(self) -> list[tuple[str, str]]:
        result = []
        while True:
            line = self.rfile.readline(65536)
            if line in (b"\r\n", b"\n", b""):
                return result
            decoded = line.decode("iso-8859-1").rstrip("\r\n")
            if ":" not in decoded:
                continue
            name, value = decoded.split(":", 1)
            result.append((name.strip(), value.strip()))

    def _handle_connect(self, target: str) -> None:
        try:
            host, port = parse_connect_target(target)
        except ValueError:
            self._send_error(400, "Invalid CONNECT target")
            return
        if not self.server.policy.allows(host, port):
            self._send_error(403, "Domain is not allowed today")
            return
        try:
            upstream = socket.create_connection((host, port), timeout=8)
        except OSError:
            self._send_error(502, "Upstream connection failed")
            return
        with upstream:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self._relay(upstream)

    def _handle_http(self, method: str, target: str, version: str, headers: list[tuple[str, str]]) -> None:
        try:
            parsed = urlsplit(target)
        except ValueError:
            self._send_error(400, "Malformed request target")
            return
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            self._send_error(400, "Proxy requires an absolute HTTP URL")
            return
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            self._send_error(400, "Invalid port in request target")
            return
        if not self.server.policy.allows(parsed.hostname, port):
            self._send_error(403, "Domain is not allowed today")
            return
        if parsed.scheme == "https":
            self._send_error(400, "HTTPS must use CONNECT")
            return
        try:
            upstream = socket.create_connection((parsed.hostname, port), timeout=8)
        except OSError:
            self._send_error(502, "Upstream connection failed")
            return
        request_path = parsed.path or "/"
        if parsed.query:
            request_path += "?" + parsed.query
        outgoing = [f"{method} {request_path} {version}\r\n"]
        for name, value in headers:
            if name.lower() not in {"proxy-connection", "connection"}:
                outgoing.append(f"{name}: {value}\r\n")
        outgoing.append("Connection: close\r\n\r\n")
        with upstream:
            upstream.sendall("".join(outgoing).encode("iso-8859-1"))
            while True:
                chunk = upstream.recv(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _relay(self, upstream: socket.socket) -> None:
        client = self.connection
        sockets = [client, upstream]
        while True:
            readable, _, _ = select.select(sockets, [], [], 30)
            if not readable:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                target = upstream if source is client else client
                target.sendall(data)

    def _send_error(self, code: int, message: str) -> None:
        body = f"{code} {message}\n".encode("utf-8")
        self.wfile.write(
            f"HTTP/1.1 {code} {message}\r\nContent-Length: {len(body)}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\nConnection: close\r\n\r\n".encode("iso-8859-1")
        )
        self.wfile.write(body)


class AllowlistProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, allowed_domains: set[str], port: int = 0):
        super().__init__(("127.0.0.1", port), _ProxyHandler)
        self.policy = ProxyPolicy(allowed_domains)

    @property
    def proxy_port(self) -> int:
        return int(self.server_address[1])
