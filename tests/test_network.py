from typing import Any

import pytest

from app.services import network


def test_host_ip_env_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST_IP", "192.168.1.50")

    def fail_socket(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("socket must not be probed when HOST_IP is set")

    monkeypatch.setattr(network.socket, "socket", fail_socket)

    assert network.detect_lan_ip() == "192.168.1.50"


def test_detect_lan_ip_falls_back_on_socket_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOST_IP", raising=False)

    def broken_socket(*args: Any, **kwargs: Any) -> Any:
        raise OSError("network is unreachable")

    monkeypatch.setattr(network.socket, "socket", broken_socket)

    assert network.detect_lan_ip() == network.FALLBACK_IP
    assert network.FALLBACK_IP == "127.0.0.1"


def test_build_download_url() -> None:
    url = network.build_download_url("192.168.1.10", 8000, "abc-123")

    assert url == "http://192.168.1.10:8000/api/tracks/abc-123/download"


def test_generate_qr_svg_returns_svg_bytes() -> None:
    data = network.generate_qr_svg(
        "http://192.168.1.10:8000/api/tracks/abc-123/download"
    )

    assert isinstance(data, bytes)
    assert b"<svg" in data
