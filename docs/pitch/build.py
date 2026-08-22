"""Inline the screenshots into deck.html as data URIs.

The template keeps the images as files so they stay reviewable; the published
artifact has to be self-contained, so this writes one file with everything in it.

    python docs/pitch/build.py
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "deck.template.html"
SHOTS = HERE / "shots"
OUT = HERE / "deck.html"


def data_uri(name: str) -> str:
    path = SHOTS / f"{name}.webp"
    if not path.exists():
        raise SystemExit(f"missing screenshot: {path}")
    return "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


html = TEMPLATE.read_text(encoding="utf-8")
used: list[str] = []


def swap(match: re.Match[str]) -> str:
    name = match.group(1)
    used.append(name)
    return data_uri(name)


html = re.sub(r"\{\{IMG:([a-z0-9-]+)\}\}", swap, html)
OUT.write_text(html, encoding="utf-8")

print(f"{OUT.name}: {OUT.stat().st_size / 1024:.0f} KB, {len(used)} images inlined")
for name in used:
    print(f"  {name}")
