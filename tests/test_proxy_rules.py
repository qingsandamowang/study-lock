import pytest
import socket
import threading

from study_lock.proxy import AllowlistProxyServer, ProxyPolicy, parse_connect_target


def test_proxy_policy_allows_only_allowlisted_domains_on_web_ports():
    policy = ProxyPolicy({"chatgpt.com"})

    assert policy.allows("chatgpt.com", 443) is True
    assert policy.allows("sub.chatgpt.com", 80) is True
    assert policy.allows("chatgpt.com", 22) is False
    assert policy.allows("example.com", 443) is False


def test_parse_connect_target_rejects_malformed_or_non_web_targets():
    assert parse_connect_target("chatgpt.com:443") == ("chatgpt.com", 443)
    with pytest.raises(ValueError):
        parse_connect_target("chatgpt.com")
    with pytest.raises(ValueError):
        parse_connect_target("chatgpt.com:22")


def test_proxy_returns_403_for_unlisted_connect_target():
    server = AllowlistProxyServer({"chatgpt.com"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(("127.0.0.1", server.proxy_port), timeout=2) as client:
            client.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n")
            response = client.recv(1024)
        assert response.startswith(b"HTTP/1.1 403")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
