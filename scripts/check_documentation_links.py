#!/usr/bin/env python3
"""Check relative Markdown links in the public documentation."""

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")
REFERENCE = re.compile(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.MULTILINE)
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def outside_fences(text):
    fence = None
    lines = []
    for line in text.splitlines():
        match = FENCE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return "\n".join(lines)


def anchors(text):
    counts = {}
    result = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', text))
    for heading in re.findall(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", outside_fences(text), re.MULTILINE):
        heading = re.sub(r"<[^>]+>", "", heading).lower()
        slug = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug if not count else f"{slug}-{count}")
    return result


def main():
    files = [ROOT / "README.md"]
    for directory in ("docs", "reports"):
        files.extend(sorted((ROOT / directory).rglob("*.md")))
    errors = []
    checked = 0
    for source in files:
        text = outside_fences(source.read_text(encoding="utf-8"))
        for raw in LINK.findall(text) + REFERENCE.findall(text):
            url = raw.strip("<>")
            parts = urlsplit(url)
            if parts.scheme or parts.netloc or url.startswith("//"):
                continue
            path = unquote(parts.path)
            target = ((ROOT / path.lstrip("/")) if path.startswith("/") else (source.parent / path)).resolve() if path else source
            checked += 1
            if not target.exists():
                errors.append(f"{source.relative_to(ROOT)}: missing {url}")
            elif parts.fragment and target.is_file() and target.suffix.lower() == ".md":
                if unquote(parts.fragment) not in anchors(target.read_text(encoding="utf-8")):
                    errors.append(f"{source.relative_to(ROOT)}: missing anchor {url}")
    for error in errors:
        print(error)
    print(f"Checked {checked} relative links in {len(files)} files; {len(errors)} errors")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
