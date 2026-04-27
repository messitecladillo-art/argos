from __future__ import annotations

from app.services import skill_frontmatter


def test_parse_without_frontmatter_returns_raw_body():
    frontmatter, body = skill_frontmatter.parse("# Title\n")

    assert frontmatter == {}
    assert body == "# Title\n"


def test_dump_roundtrip_preserves_frontmatter_and_body():
    content = skill_frontmatter.dump(
        {"name": "demo", "description": "Demo skill"},
        "# Demo\n",
    )

    frontmatter, body = skill_frontmatter.parse(content)

    assert frontmatter["name"] == "demo"
    assert frontmatter["description"] == "Demo skill"
    assert body == "# Demo\n"


def test_parse_accepts_crlf_frontmatter():
    frontmatter, body = skill_frontmatter.parse(
        "---\r\nname: demo\r\ndescription: Demo skill\r\n---\r\n\r\n# Demo\r\n"
    )

    assert frontmatter["name"] == "demo"
    assert frontmatter["description"] == "Demo skill"
    assert body == "\r\n# Demo\r\n"
