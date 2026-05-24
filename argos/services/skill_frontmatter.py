from __future__ import annotations

import re

import yaml


def parse(content: str) -> tuple[dict, str]:
    text = content or ""
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?", text, re.DOTALL)
    if not match:
        return {}, text
    raw_frontmatter = match.group(1)
    body = text[match.end() :]
    data = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(data, dict):
        data = {}
    return data, body


def dump(frontmatter: dict, body: str) -> str:
    payload = yaml.safe_dump(frontmatter or {}, allow_unicode=True, sort_keys=False).strip()
    markdown = f"---\n{payload}\n---\n"
    markdown += body or ""
    if markdown and not markdown.endswith("\n"):
        markdown += "\n"
    return markdown
