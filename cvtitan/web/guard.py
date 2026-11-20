"""Protección de la web local contra CSRF y DNS rebinding.

La app solo escucha en 127.0.0.1, pero cualquier página que abras en el navegador puede intentar llamarla.
- Las acciones que modifican datos (POST/PUT/PATCH/DELETE) exigen el encabezado `X-Titan-Token` con un token que
  se genera en cada arranque y solo se entrega dentro de la página principal.
- Se rechazan los encabezados `Host` que no sean localhost (ataques de DNS rebinding) y los `Origin` ajenos.
"""
from __future__ import annotations

import hmac
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def host_of(value: str | None) -> str:
    """'127.0.0.1:8765' -> '127.0.0.1'; '[::1]:8765' -> '::1'."""
    if not value:
        return ""
    value = value.strip()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.split(":", 1)[0].lower()


def host_ok(value: str | None) -> bool:
    return host_of(value) in ALLOWED_HOSTS


def origin_ok(origin: str | None) -> bool:
    """Sin Origin (peticiones directas, curl, pruebas) se permite; con Origin debe ser localhost."""
    if not origin or origin == "null":
        return not origin
    return host_ok(urlparse(origin).netloc)


def inject_token(html: str, token: str) -> str:
    meta = f'<meta name="titan-token" content="{token}">'
    return html.replace("</head>", meta + "\n</head>", 1)


def install(app: FastAPI, token: str) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not host_ok(request.headers.get("host")):
            return JSONResponse({"detail": "Host no permitido."}, status_code=403)
        if request.method in UNSAFE_METHODS:
            if not origin_ok(request.headers.get("origin")):
                return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
            if not hmac.compare_digest(request.headers.get("x-titan-token", ""), token):
                return JSONResponse({"detail": "Token de sesión inválido: recarga la página."}, status_code=403)
        return await call_next(request)
