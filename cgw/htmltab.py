"""Minimal nesting-aware HTML table extractor (stdlib only).

Wikipedia's GPU lists wrap sub-tables inside cells, which defeats regex-based
table scraping. This walks the token stream, keeps a stack of open tables and
attaches each cell to the innermost open table, so a parent-row cell never
swallows the text of a nested table.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Optional

# Tags that implicitly close an open cell.
_CELL_CLOSERS = {"td", "th", "tr", "table", "tbody", "thead", "tfoot", "caption"}
_BLOCK_TAGS = {"br", "p", "div", "li"}


class Cell:
    __slots__ = ("text", "colspan", "rowspan", "is_header", "links")

    def __init__(self, is_header: bool = False, colspan: int = 1, rowspan: int = 1):
        self.text = ""
        self.colspan = colspan
        self.rowspan = rowspan
        self.is_header = is_header
        self.links: list[str] = []

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Cell({self.text!r}, h={self.is_header})"


class Row:
    __slots__ = ("cells",)

    def __init__(self) -> None:
        self.cells: list[Cell] = []

    @property
    def text(self) -> str:
        return " | ".join(c.text for c in self.cells)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Row({self.text!r})"


class Table:
    __slots__ = ("rows", "attrs", "caption")

    def __init__(self, attrs: dict):
        self.rows: list[Row] = []
        self.attrs = attrs
        self.caption = ""

    def headers(self) -> list[str]:
        for row in self.rows:
            if any(c.is_header for c in row.cells):
                return [c.text.strip().lower() for c in row.cells]
        return []

    def body_rows(self) -> list[Row]:
        """Rows that are not the header row."""
        return [r for r in self.rows if not (r.cells and all(c.is_header for c in r.cells))]

    def header_index(self, *names: str) -> Optional[int]:
        hdr = self.headers()
        for i, h in enumerate(hdr):
            for n in names:
                if n in h:
                    return i
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"Table(rows={len(self.rows)}, headers={self.headers()})"


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self._stack: list[Table] = []
        self._cur_row: Optional[Row] = None
        self._cur_cell: Optional[Cell] = None
        self._skip_depth = 0  # inside <script>/<style>

    # -- helpers ---------------------------------------------------------
    def _close_cell(self) -> None:
        if self._cur_cell is not None and self._cur_row is not None:
            self._cur_cell.text = " ".join(self._cur_cell.text.split())
            self._cur_row.cells.append(self._cur_cell)
        self._cur_cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self._cur_row is not None and self._stack:
            if self._cur_row.cells:
                self._stack[-1].rows.append(self._cur_row)
        self._cur_row = None

    # -- parser hooks ----------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if tag == "table":
            self._close_row()
            t = Table(a)
            self._stack.append(t)
            self.tables.append(t)
            return
        if not self._stack:
            return
        if tag in _CELL_CLOSERS and tag != "table":
            if tag == "tr":
                self._close_row()
                self._cur_row = Row()
            elif tag in ("td", "th"):
                self._close_cell()
                if self._cur_row is None:
                    self._cur_row = Row()
                try:
                    cs = int(a.get("colspan", "1"))
                except ValueError:
                    cs = 1
                try:
                    rs = int(a.get("rowspan", "1"))
                except ValueError:
                    rs = 1
                self._cur_cell = Cell(is_header=(tag == "th"), colspan=cs, rowspan=rs)
        elif tag == "caption" and len(self._stack):
            self._stack[-1].caption = ""  # text captured below
        elif tag in _BLOCK_TAGS and self._cur_cell is not None:
            self._cur_cell.text += " "

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in ("br", "hr") and self._cur_cell is not None:
            self._cur_cell.text += " "

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "table":
            self._close_row()
            if self._stack:
                self._stack.pop()
            return
        if not self._stack:
            return
        if tag in ("td", "th"):
            self._close_cell()
        elif tag == "tr":
            self._close_row()

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not self._stack:
            return
        if self._cur_cell is not None:
            self._cur_cell.text += data


def parse_tables(html: str) -> list[Table]:
    p = _TableParser()
    p.feed(html)
    p.close()
    return [t for t in p.tables if t.rows]


def strip_tags(html: str) -> str:
    """Collapse an HTML fragment to whitespace-normalised text."""
    out: list[str] = []

    class _S(HTMLParser):
        def handle_data(self, d):
            out.append(d)

    s = _S(convert_charrefs=True)
    s.feed(html)
    return " ".join(" ".join(out).split())
