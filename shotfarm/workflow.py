"""Fill ComfyUI API-format workflow templates.

Export your H3 workflow from ComfyUI with "Save (API Format)", then replace the
values you want ShotFarm to control with placeholders:

    "{{PROMPT}}"  "{{SECONDS}}"  "{{SEED}}"  "{{WIDTH}}"  "{{HEIGHT}}"
    "{{FIRST_FRAME}}"  "{{LAST_FRAME}}"  "{{REF_AUDIO}}"

A placeholder that is the whole string value is replaced with a typed value
(numbers stay numbers). Placeholders inside longer strings are substituted as text.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

_WHOLE = re.compile(r"^\{\{([A-Z_]+)\}\}$")
_INLINE = re.compile(r"\{\{([A-Z_]+)\}\}")


def load_template(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def fill(template: dict, values: dict) -> dict:
    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            m = _WHOLE.match(node)
            if m:
                key = m.group(1)
                if key not in values:
                    raise KeyError(f"template needs {{{{{key}}}}} but no value was given")
                return values[key]
            return _INLINE.sub(lambda m: str(values[m.group(1)]), node)
        return node

    return walk(copy.deepcopy(template))


def placeholders(template: dict) -> set[str]:
    return set(_INLINE.findall(json.dumps(template)))
