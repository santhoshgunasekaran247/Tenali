import os
import re
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send


class PublicOriginMiddleware:
    """Restore a fixed public origin for a separate static site's API rewrite."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.api_host = os.getenv("TENALI_API_HOST", "").strip().lower()
        public_origin = os.getenv("TENALI_PUBLIC_ORIGIN", "").strip()
        self.public = urlsplit(public_origin)
        if not self.api_host and not public_origin:
            return
        if not self.api_host or not public_origin:
            raise ValueError("TENALI_API_HOST and TENALI_PUBLIC_ORIGIN must be configured together")
        hostname_pattern = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*"
        if not re.fullmatch(hostname_pattern, self.api_host):
            raise ValueError("TENALI_API_HOST must be an exact hostname, without scheme, path or port")
        if (
            self.public.scheme != "https"
            or not self.public.hostname
            or not re.fullmatch(hostname_pattern, self.public.hostname)
            or self.public.netloc.lower() != self.public.hostname
            or self.public.path not in {"", "/"}
            or self.public.query
            or self.public.fragment
        ):
            raise ValueError("TENALI_PUBLIC_ORIGIN must be an HTTPS origin without credentials, port or path")
        base = os.getenv("TENALI_BASE_DOMAIN", "").strip(".").lower()
        if not base or self.public.hostname not in {base, "app." + base}:
            raise ValueError("TENALI_PUBLIC_ORIGIN must match TENALI_BASE_DOMAIN or its app subdomain")

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if self.api_host and scope["type"] in {"http", "websocket"}:
            host = next((value for key, value in scope["headers"] if key.lower() == b"host"), b"")
            if host.decode("latin-1").lower() == self.api_host:
                scope = dict(scope)
                # Never derive the public host from caller-supplied forwarding headers.
                scope["headers"] = [
                    (key, value) for key, value in scope["headers"] if key.lower() != b"host"
                ] + [(b"host", self.public.netloc.lower().encode("ascii"))]
                scope["scheme"] = "wss" if scope["type"] == "websocket" else "https"
                scope["server"] = (self.public.hostname, 443)
        await self.app(scope, receive, send)
