"""Safe, request-scoped HTTPS transport primitives for model providers."""
from __future__ import annotations

import codecs
import http.client
import ipaddress
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Iterator
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ResolvedEndpoint:
    hostname: str
    address: str
    port: int
    request_target: str


def resolve_public_endpoint(url: str) -> ResolvedEndpoint:
    """Resolve once and reject any DNS answer that could reach a local network."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("model endpoint is invalid") from exc
    if port is None:
        port = 443
    elif not 1 <= port <= 65535:
        raise ValueError("model endpoint port is invalid")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("model endpoint must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("model endpoint is invalid")
    hostname = parsed.hostname.rstrip(".")
    if not hostname or "%" in hostname:
        raise ValueError("model endpoint is invalid")

    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal.compressed]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except OSError:
            raise ValueError("model endpoint could not be resolved safely") from None
        addresses = []
        for record in records:
            sockaddr = record[4]
            if not sockaddr:
                continue
            address = sockaddr[0].split("%", 1)[0]
            if address not in addresses:
                addresses.append(address)

    if not addresses:
        raise ValueError("model endpoint could not be resolved safely")
    parsed_addresses = []
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise ValueError("model endpoint resolved to an invalid address") from None
        if not address.is_global:
            raise ValueError("model endpoint resolved to a local or reserved address")
        parsed_addresses.append(address.compressed)

    path = parsed.path or "/"
    return ResolvedEndpoint(hostname=hostname, address=parsed_addresses[0], port=port, request_target=path)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, pinned_address: str, *args, **kwargs) -> None:
        super().__init__(host, *args, **kwargs)
        self._pinned_address = pinned_address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self.sock = raw_socket
            self._tunnel()
        server_hostname = self.host if self._context.check_hostname else None
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=server_hostname)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, resolved: ResolvedEndpoint) -> None:
        super().__init__()
        self._resolved = resolved

    def https_open(self, request):
        try:
            parsed = urlsplit(request.full_url)
            request_port = parsed.port or 443
        except ValueError as exc:
            raise urllib.error.URLError("model endpoint is invalid") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != self._resolved.hostname
            or request_port != self._resolved.port
            or parsed.path != self._resolved.request_target
            or parsed.query
            or parsed.fragment
        ):
            raise urllib.error.URLError("model endpoint changed after validation")
        return self.do_open(
            lambda host, **kwargs: _PinnedHTTPSConnection(host, self._resolved.address, **kwargs),
            request,
            context=self._context,
            check_hostname=self._check_hostname,
        )


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(request.full_url, code, "redirect refused", headers, fp)


def open_model_request(request: urllib.request.Request, timeout: float = 30.0):
    """Open a request without proxies or redirects, pinning HTTPS DNS to a public IP."""
    if not isinstance(request, urllib.request.Request):
        raise TypeError("request must be urllib.request.Request")
    resolved = resolve_public_endpoint(request.full_url)
    # urllib honors a supplied Host header verbatim. Derive it from the URL
    # that was just validated so callers cannot route the pinned connection
    # under an unrelated HTTP authority.
    host = f"[{resolved.hostname}]" if ":" in resolved.hostname else resolved.hostname
    if resolved.port != 443:
        host = f"{host}:{resolved.port}"
    for headers in (request.headers, request.unredirected_hdrs):
        for name in list(headers):
            if name.lower() == "host":
                del headers[name]
    request.add_unredirected_header("Host", host)
    request.timeout = timeout
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _PinnedHTTPSHandler(resolved),
        NoRedirectHandler(),
    )
    return opener.open(request, timeout=timeout)


def iter_sse_data(response: Iterable[bytes | str]) -> Iterator[str]:
    """Yield complete SSE data payloads, tolerating arbitrary chunk boundaries."""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buffer = ""
    data_lines: list[str] = []

    def consume_line(line: str) -> str | None:
        if line == "":
            if not data_lines:
                return None
            value = "\n".join(data_lines)
            data_lines.clear()
            return value if value != "[DONE]" else None
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)
        return None

    def complete_lines(final: bool = False) -> Iterator[str]:
        nonlocal buffer
        while buffer:
            newline = min((position for position in (buffer.find("\r"), buffer.find("\n")) if position >= 0), default=-1)
            if newline < 0:
                break
            if buffer[newline] == "\r" and newline + 1 == len(buffer) and not final:
                break
            width = 2 if buffer[newline:newline + 2] == "\r\n" else 1
            line = buffer[:newline]
            buffer = buffer[newline + width:]
            value = consume_line(line)
            if value is not None:
                yield value
        if final:
            if buffer:
                value = consume_line(buffer)
                buffer = ""
                if value is not None:
                    yield value
            if data_lines:
                value = "\n".join(data_lines)
                data_lines.clear()
                if value != "[DONE]":
                    yield value

    bytes_decoder_pending = False
    for chunk in response:
        if isinstance(chunk, bytes):
            buffer += decoder.decode(chunk, final=False)
            bytes_decoder_pending = True
        else:
            if bytes_decoder_pending:
                buffer += decoder.decode(b"", final=True)
                decoder = codecs.getincrementaldecoder("utf-8")("replace")
                bytes_decoder_pending = False
            buffer += str(chunk)
        yield from complete_lines()
    if bytes_decoder_pending:
        buffer += decoder.decode(b"", final=True)
    yield from complete_lines(final=True)
