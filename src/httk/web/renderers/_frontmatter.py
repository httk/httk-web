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
                # Normalize "*-list" keys (e.g. "menuitems-list") to match RstRenderer
                # behavior: strip the "-list" suffix and ensure the value is a list.
                normalized: dict[str, Any] = {}
                for key, value in loaded.items():
                    if isinstance(key, str) and key.endswith("-list"):
                        base_key = key[:-5]
                        existing = normalized.get(base_key)
                        if existing is None:
                            normalized[base_key] = []
                        elif not isinstance(existing, list):
                            normalized[base_key] = [existing]
                        target_list = normalized[base_key]
                        if isinstance(value, list):
                            target_list.extend(value)
                        elif value is not None:
                            target_list.append(value)
                    else:
                        normalized[key] = value
                return normalized, body
            return {}, body

    return {}, text
