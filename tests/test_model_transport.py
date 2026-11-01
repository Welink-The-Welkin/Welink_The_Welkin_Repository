import socket
import ssl
import urllib.error
import urllib.request

import pytest
from backend.app.contracts.model import ModelConfig, FreeChatRequest, ProviderPreset, ModelTestResult
from backend.app.core.model_transport import (
    NoRedirectHandler,
    ResolvedEndpoint,
    _PinnedHTTPSConnection,
    iter_sse_data,
    open_model_request,
    resolve_public_endpoint,
)


def test_model_config_rejects_http_private_and_embedded_credentials():
    for url in (
        "http://provider.example/v1",
        "https://127.0.0.1/v1",
        "https://192.168.1.10/v1",
        "https://user:pass@provider.example/v1",
    ):
        with pytest.raises(ValueError):
            ModelConfig.from_payload({"endpoint": url, "model": "demo", "api_key": "secret"})


def test_model_config_does_not_expose_key_in_repr_or_diagnostic_endpoint():
    config = ModelConfig.from_payload({
        "endpoint": "https://provider.example/v1",
        "model": "demo",
        "api_key": "secret-key",
    })
    assert "secret-key" not in repr(config)
    assert "api_key" not in config.model_dump()
    assert "secret-key" not in str(config.model_dump())
    assert config.diagnostic_endpoint == "https://provider.example/v1/chat/completions"


def test_sse_parser_handles_multiline_data_and_done_marker():
    frames = list(iter_sse_data([
        b"data: {\"a\":\n",
        b"data: 1}\r\n\r\n",
        b"data: [DONE]\n\n",
    ]))
    assert frames == ['{"a":\n1}']


def test_model_config_rejects_invalid_model_and_query_fragment():
    for model in ("", "bad model", "../secret", "a/b"):
        with pytest.raises(ValueError):
            ModelConfig.from_payload({"endpoint": "https://provider.example/v1", "model": model, "api_key": "x"})
    for endpoint in ("https://provider.example/v1?token=x", "https://provider.example/v1#frag"):
        with pytest.raises(ValueError):
            ModelConfig.from_payload({"endpoint": endpoint, "model": "demo", "api_key": "x"})


def test_sse_parser_flushes_empty_and_final_frames():
    assert list(iter_sse_data(["data: one\n\n", "data: two"])) == ["one", "two"]
    assert list(iter_sse_data(["event: ignored\n\n", "\n"])) == []


def test_provider_error_public_mapping_and_retry_after():
    from backend.app.core.errors import ModelProviderError
    error = ModelProviderError("internal", status_code=429, retry_after="12.7", provider_code="rate_limit")
    assert error.retry_after == 12.7
    assert error.public_message == "模型服务当前限流或账户额度不足（HTTP 429）。请稍后重试，或检查服务商账户额度。"


def test_public_endpoint_resolves_only_public_addresses_and_keeps_hostname(monkeypatch):
    monkeypatch.setattr(
        "backend.app.core.model_transport.socket.getaddrinfo",
        lambda host, port, type: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))],
    )

    resolved = resolve_public_endpoint("https://provider.example/v1/chat/completions")

    assert resolved.hostname == "provider.example"
    assert resolved.address == "93.184.216.34"
    assert resolved.port == 443
    assert resolved.request_target == "/v1/chat/completions"


def test_public_endpoint_rejects_dns_results_that_include_private_addresses(monkeypatch):
    monkeypatch.setattr(
        "backend.app.core.model_transport.socket.getaddrinfo",
        lambda host, port, type: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", port)),
        ],
    )

    with pytest.raises(ValueError):
        resolve_public_endpoint("https://provider.example/v1")


def test_pinned_https_connection_connects_to_validated_ip_and_uses_original_sni(monkeypatch):
    captured = {}

    class FakeSocket:
        def close(self):
            pass

    class FakeContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, sock, *, server_hostname):
            captured["server_hostname"] = server_hostname
            return sock

    def create_connection(address, timeout=None, source_address=None):
        captured["address"] = address
        return FakeSocket()

    monkeypatch.setattr("backend.app.core.model_transport.socket.create_connection", create_connection)
    connection = _PinnedHTTPSConnection(
        "provider.example",
        "93.184.216.34",
        port=443,
        context=FakeContext(),
    )

    connection.connect()

    assert captured["address"] == ("93.184.216.34", 443)
    assert captured["server_hostname"] == "provider.example"
    assert connection.host == "provider.example"


def test_redirect_handler_rejects_location_redirects():
    handler = NoRedirectHandler()
    request = urllib.request.Request("https://provider.example/v1")

    with pytest.raises(urllib.error.HTTPError) as error:
        handler.redirect_request(request, None, 302, "Found", {}, "https://127.0.0.1/private")

    assert error.value.code == 302
    assert "127.0.0.1" not in str(error.value)


def test_open_model_request_overrides_caller_host_with_validated_url_host(monkeypatch):
    resolved = ResolvedEndpoint(
        hostname="provider.example",
        address="93.184.216.34",
        port=443,
        request_target="/v1/chat/completions",
    )
    monkeypatch.setattr("backend.app.core.model_transport.resolve_public_endpoint", lambda url: resolved)
    captured = {}

    class FakeOpener:
        def open(self, request, *, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return object()

    def build_opener(*handlers):
        captured["handlers"] = handlers
        return FakeOpener()

    monkeypatch.setattr("backend.app.core.model_transport.urllib.request.build_opener", build_opener)
    request = urllib.request.Request(
        "https://provider.example/v1/chat/completions",
        headers={"Host": "attacker.example"},
        method="POST",
    )

    open_model_request(request)

    sent_headers = dict(captured["request"].header_items())
    assert sent_headers["Host"] == "provider.example"
    assert captured["handlers"][1]._resolved is resolved


def test_open_model_request_resolves_once_and_pins_that_public_address(monkeypatch):
    calls = []
    captured = {}

    def getaddrinfo(host, port, *, type):
        calls.append((host, port, type))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    class FakeOpener:
        def open(self, request, *, timeout):
            return object()

    def build_opener(*handlers):
        captured["handlers"] = handlers
        return FakeOpener()

    monkeypatch.setattr("backend.app.core.model_transport.socket.getaddrinfo", getaddrinfo)
    monkeypatch.setattr("backend.app.core.model_transport.urllib.request.build_opener", build_opener)
    request = urllib.request.Request("https://provider.example/v1/chat/completions", method="POST")

    open_model_request(request)

    assert calls == [("provider.example", 443, socket.SOCK_STREAM)]
    assert captured["handlers"][1]._resolved.address == "93.184.216.34"
