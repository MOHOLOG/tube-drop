import os
import socket

import segno

FALLBACK_IP = "127.0.0.1"
PROBE_ADDRESS = ("8.8.8.8", 80)
PROBE_TIMEOUT_SEC = 1.0


def detect_lan_ip() -> str:
    host_ip = os.getenv("HOST_IP", "").strip()
    if host_ip:
        return host_ip

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(PROBE_TIMEOUT_SEC)
            sock.connect(PROBE_ADDRESS)
            return sock.getsockname()[0]
    except OSError:
        return FALLBACK_IP


def build_download_url(ip: str, port: int, track_id: str) -> str:
    return f"http://{ip}:{port}/api/tracks/{track_id}/download"


def generate_qr_svg(url: str) -> bytes:
    svg = segno.make(url).svg_inline(omitsize=True)
    return svg.encode("utf-8")
