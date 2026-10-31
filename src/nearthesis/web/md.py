"""A small, deterministic Markdown-to-HTML renderer for the subset used in thesis/THESIS.md.

Supported: ATX headings (with ids), paragraphs, unordered and ordered lists (one level, continuation lines),
pipe tables, fenced code blocks, block quotes, horizontal rules, HTML comments (dropped), and inline code, bold,
italic and links. Everything else is escaped. No third-party dependency, so the site build stays in the lock file.
"""

from __future__ import annotations

import html
import re

_INLINE_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])")


def slug(text: str) -> str:
    s = re.sub(r"<[^>]+>", "", text).lower()
    s = re.sub(r"[^a-z0-9 -]", "", s).strip().replace(" ", "-")
    return re.sub(r"-+", "-", s)


def inline(text: str, link_map=None) -> str:
    """Escape, then apply code spans (protected), links, bold and italics."""
    codes: list[str] = []

    def keep(m: re.Match) -> str:
        codes.append(f"<code>{html.escape(m.group(1), quote=False)}</code>")
        return f"\x00{len(codes) - 1}\x00"
    t = _INLINE_CODE.sub(keep, text)
    t = html.escape(t, quote=False)

    def link(m: re.Match) -> str:
        href = m.group(2)
        if link_map:
            href = link_map(href)
        return f'<a href="{html.escape(href)}">{m.group(1)}</a>'
    t = _LINK.sub(link, t)
    t = _BOLD.sub(r"<strong>\1</strong>", t)
    t = _ITAL.sub(r"<em>\1</em>", t)
    return re.sub("\x00(\\d+)\x00", lambda m: codes[int(m.group(1))], t)


def _table(lines: list[str], link_map) -> str:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]
    head = cells(lines[0])
    aligns = []
    for c in cells(lines[1]):
        aligns.append("right" if c.endswith(":") and not c.startswith(":") else "")
    out = ['<div class="table-wrap"><table>', "<thead><tr>"]
    out += [f"<th>{inline(h, link_map)}</th>" for h in head]
    out.append("</tr></thead><tbody>")
    for line in lines[2:]:
        out.append("<tr>" + "".join(
            f'<td{" class=num" if (i < len(aligns) and aligns[i]) else ""}>{inline(c, link_map)}</td>'
            for i, c in enumerate(cells(line))) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render(md: str, link_map=None) -> tuple[str, list[tuple[int, str, str]]]:
    """Returns (html, headings) where headings are (level, id, text) for a table of contents."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    lines = md.split("\n")
    out: list[str] = []
    heads: list[tuple[int, str, str]] = []
    i, n = 0, len(lines)
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(s.strip() for s in para), link_map)}</p>")
            para.clear()

    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            flush()
            i += 1
            continue
        if s.startswith("```"):
            flush()
            j = i + 1
            while j < n and not lines[j].strip().startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j]), quote=False) + "</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            flush()
            level, text = len(m.group(1)), m.group(2).strip()
            hid = slug(text)
            heads.append((level, hid, text))
            out.append(f'<h{level} id="{hid}">{inline(text, link_map)}</h{level}>')
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", s):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if s.startswith("|") and i + 1 < n and re.match(r"^\|?\s*:?-{3,}", lines[i + 1].strip()):
            flush()
            j = i
            while j < n and lines[j].strip().startswith("|"):
                j += 1
            out.append(_table(lines[i:j], link_map))
            i = j
            continue
        if s.startswith(">"):
            flush()
            j, buf = i, []
            while j < n and lines[j].strip().startswith(">"):
                buf.append(lines[j].strip()[1:].strip())
                j += 1
            inner, _ = render("\n".join(buf), link_map)
            out.append(f"<blockquote>{inner}</blockquote>")
            i = j
            continue
        lm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if lm:
            flush()
            ordered = lm.group(2)[0].isdigit()
            items: list[str] = []
            j = i
            while j < n:
                cur = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[j])
                if cur and (cur.group(2)[0].isdigit()) == ordered and len(cur.group(1)) <= 1:
                    items.append(cur.group(3).strip())
                    j += 1
                elif lines[j].startswith("  ") and lines[j].strip() and items:
                    items[-1] += " " + lines[j].strip()
                    j += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(it, link_map)}</li>" for it in items) + f"</{tag}>")
            i = j
            continue
        para.append(line)
        i += 1
    flush()
    return "\n".join(out), heads
