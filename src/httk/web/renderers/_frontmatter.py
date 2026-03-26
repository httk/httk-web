from typing import Any

import yaml


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines:
        return {}, text

    first = lines[0].strip()
    if first not in {"---", "--------", "-----"}:
        return {}, text

    for i in range(1, len(lines)):
        if lines[i].strip() == first:
            frontmatter_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            loaded = yaml.safe_load(frontmatter_text)
            if loaded is None:
                return {}, body
            if isinstance(loaded, dict):
                return loaded, body
            return {}, body

    return {}, text
