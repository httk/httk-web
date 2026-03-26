from pathlib import Path

from docutils import nodes
from docutils.core import publish_doctree, publish_parts
from docutils.writers.html5_polyglot import Writer

from .base import RenderResult


class RstRenderer:
    def render(self, source_path: Path) -> RenderResult:
        source = source_path.read_text(encoding="utf-8")

        html = publish_parts(source, writer=Writer()).get("html_body", "")
        metadata = self._extract_metadata(source)
        return RenderResult(html=html, metadata=metadata)

    def _extract_metadata(self, source: str) -> dict[str, object]:
        doctree = publish_doctree(source)
        metadata: dict[str, object] = {}

        for field in doctree.findall(nodes.field):
            if len(field.children) < 2:
                continue

            name_node = field.children[0]
            body_node = field.children[1]
            name = name_node.astext().strip().lower()

            if name.endswith("-list"):
                key = name[: -len("-list")]
                values: list[str] = []
                for item in body_node.findall(nodes.list_item):
                    text = item.astext().strip()
                    if text:
                        values.append(text)
                if not values:
                    text = body_node.astext().strip()
                    values = [x.strip() for x in text.splitlines() if x.strip()]
                metadata[key] = values
            else:
                metadata[name] = body_node.astext().strip()

        return metadata
