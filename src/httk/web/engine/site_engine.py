from html import escape
from mimetypes import guess_type

from httk.web.engine.discovery import resolve_route
from httk.web.model.config import SiteConfig
from httk.web.model.errors import NotFoundError
from httk.web.model.page import PageResult, ResolvedRoute


class SiteEngine:
    def __init__(self, config: SiteConfig) -> None:
        self.config = config

    def resolve(self, route: str) -> ResolvedRoute:
        return resolve_route(config=self.config, route=route)

    def render(self, route: str) -> PageResult:
        resolved = self.resolve(route)

        if resolved.kind == "missing" or resolved.source_path is None:
            raise NotFoundError(f"Route not found: {resolved.route}")

        if resolved.kind == "static":
            content_type = guess_type(str(resolved.source_path))[0] or "application/octet-stream"
            return PageResult(status_code=200, content_type=content_type, body=resolved.source_path.read_bytes())

        suffix = resolved.source_path.suffix.lower()
        if suffix == ".html":
            content = resolved.source_path.read_bytes()
            return PageResult(status_code=200, content_type="text/html; charset=utf-8", body=content)

        text = resolved.source_path.read_text(encoding="utf-8")
        html = f"<pre>{escape(text)}</pre>".encode("utf-8")
        return PageResult(status_code=200, content_type="text/html; charset=utf-8", body=html)
