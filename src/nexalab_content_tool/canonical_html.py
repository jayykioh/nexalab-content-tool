from __future__ import annotations

import html
import re


def _table(match: re.Match[str]) -> str:
    rows = re.findall(r"\|([^\n]*)\|", match.group(0))
    cells = [[cell.strip() for cell in row.split("|")] for row in rows]
    cells = [row for row in cells if row and not all(re.fullmatch(r":?-{2,}:?", cell) for cell in row)]
    if not cells:
        return ""
    width = max(len(row) for row in cells)
    cells = [row + [""] * (width - len(row)) for row in cells]
    head, body = cells[0], cells[1:]
    th = "".join(f"<th>{html.escape(cell)}</th>" for cell in head)
    rows_html = "".join("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>" for row in body)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{rows_html}</tbody></table>"


def normalize_lesson_html(value: str) -> str:
    text = str(value or "").replace("\\- ", "").replace("\\-", "")
    text = re.sub(r"<h2>\s*\?\s*</h2>", "<h3>Câu hỏi thảo luận</h3>", text, flags=re.I)
    text = re.sub(r"(?:<p>\s*)?(?:\|[^\n<]*\|\s*(?:</p>\s*<p>|\n))+\|[^\n<]*\|(?:\s*</p>)?", _table, text)
    text = re.sub(r"<p>\s*(Mô tả hình\s*:[\s\S]*?)\s*</p>", r'<figure class="figure-note"><figcaption>\1</figcaption></figure>', text, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


