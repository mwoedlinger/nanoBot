"""Message formatting: markdown → Telegram HTML, tool notifications, table rendering."""

import re

import markdown as md_lib

from .config import TOOL_EMOJI


def format_tool_notification(name: str, inp: dict) -> str:
    """Format a tool-use event into a short emoji-prefixed notification."""
    emoji = TOOL_EMOJI.get(name, "⚙️")
    if name == "Bash":
        return f"{emoji} {inp.get('command', '').replace(chr(10), ' ')[:100]}"
    if name in ("Read", "Write", "Edit"):
        return f"{emoji} {name}: {inp.get('file_path', '')}"
    if name == "Glob":
        return f"{emoji} Glob: {inp.get('pattern', '')}"
    if name == "Grep":
        return f"{emoji} Grep: {inp.get('pattern', '')}"
    target = inp.get("url") or inp.get("query") or ""
    return f"{emoji} {name}: {str(target)[:100]}"


def _table_to_ascii(table_html: str) -> str:
    """Convert an HTML <table> to a Unicode box-drawing string."""
    rows: list[list[str]] = []
    header_rows = 0
    for row_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL):
        row_html = row_m.group(1)
        is_header = bool(re.search(r"<th\b", row_html))
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row_html, re.DOTALL)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if cells:
            rows.append(cells)
            if is_header:
                header_rows += 1
    if not rows:
        return ""
    n_cols = max(len(r) for r in rows)
    widths = [max(len(r[i]) if i < len(r) else 0 for r in rows) for i in range(n_cols)]

    def fmt_row(cells: list[str]) -> str:
        parts = [f" {(cells[i] if i < len(cells) else '').ljust(widths[i])} " for i in range(n_cols)]
        return "│" + "│".join(parts) + "│"

    def rule(l: str, m: str, r: str) -> str:
        return l + m.join("─" * (w + 2) for w in widths) + r

    lines = [rule("┌", "┬", "┐")]
    for i, row in enumerate(rows):
        lines.append(fmt_row(row))
        if i == header_rows - 1 < len(rows) - 1:
            lines.append(rule("├", "┼", "┤"))
    lines.append(rule("└", "┴", "┘"))
    return "\n".join(lines)


def md_to_html(text: str) -> str:
    """Convert markdown to Telegram-compatible HTML.

    Telegram supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <blockquote>.
    Everything else is converted to an equivalent or stripped.
    """
    out = md_lib.markdown(text, extensions=["fenced_code", "tables"])

    # Inline styles
    out = out.replace("<strong>", "<b>").replace("</strong>", "</b>")
    out = out.replace("<em>", "<i>").replace("</em>", "</i>")

    # Headers → bold
    for i in range(1, 7):
        out = out.replace(f"<h{i}>", "<b>").replace(f"</h{i}>", "</b>\n")

    # Fenced code blocks
    out = re.sub(r"<pre><code[^>]*>(.*?)</code></pre>", r"<pre>\1</pre>", out, flags=re.DOTALL)

    # Line breaks and paragraphs
    out = out.replace("<br />", "\n").replace("<br>", "\n")
    out = re.sub(r"<p>(.*?)</p>", r"\1\n\n", out, flags=re.DOTALL)

    # Lists
    out = re.sub(r"<[ou]l>\s*", "", out)
    out = re.sub(r"\s*</[ou]l>", "\n", out)
    out = re.sub(r"<li>(.*?)</li>", r"• \1\n", out, flags=re.DOTALL)

    # Horizontal rules
    out = re.sub(r"<hr\s*/?>", "─────\n", out)

    # Tables → Unicode box-art in <pre>
    out = re.sub(
        r"<table>(.*?)</table>",
        lambda m: "<pre>" + _table_to_ascii(m.group(0)) + "</pre>",
        out,
        flags=re.DOTALL,
    )

    # Strip any remaining unsupported tags, preserving their content
    out = re.sub(
        r"<(?!/?(?:b|i|u|s|del|code|pre|a|blockquote)\b)[a-z][^>]*>",
        "",
        out,
        flags=re.IGNORECASE,
    )

    return out.strip()
