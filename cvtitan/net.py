"""Cliente HTTP compartido (conexiones persistentes) para todas las descargas de TITAN CV.

Reutilizar conexiones TLS por host ahorra el apretón de manos en cada consulta: medido el 2026-11-18,
40 búsquedas en paralelo pasan de 4,2 s (urllib) a 3,0-3,3 s. Si httpx no está instalado se usa urllib.
"""
from __future__ import annotations

import threading
import urllib.request

_lock = threading.Lock()
_client = None


def _get_client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                import httpx
                _client = httpx.Client(follow_redirects=True, timeout=30,
                                       limits=httpx.Limits(max_connections=48, max_keepalive_connections=48))
    return _client


def _urllib_get(url: str, headers: dict | None, timeout: float) -> tuple[bytes, str | None]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get_content_charset()


def fetch(url: str, headers: dict | None = None, timeout: float = 30) -> tuple[bytes, str | None]:
    """GET -> (cuerpo, charset). Lanza excepción ante errores HTTP (como urllib).

    Si httpx no logra ni conectar (ConnectTimeout/ConnectError: p. ej. jobbank.gc.ca, que responde a urllib y a curl
    pero deja colgado el apretón TLS de httpx), se reintenta una vez con urllib en vez de dar la fuente por perdida."""
    try:
        import httpx
        client = _get_client()
    except ImportError:
        return _urllib_get(url, headers, timeout)
    try:
        r = client.get(url, headers=headers or {}, timeout=timeout)
    except (httpx.ConnectTimeout, httpx.ConnectError):
        return _urllib_get(url, headers, timeout)
    r.raise_for_status()
    return r.content, r.charset_encoding
