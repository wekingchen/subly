"""账单 HTML 表格提取：标准库 html.parser，双通道模式。

真实银行账单两类结构并存（探索结论）：
- 建行/平安/中信：数据表行 td 直接含文本（可能有整页布局表格包裹），
  需要「直接子级」模式——每个 td 归属最近的已开 tr
- 民生/招行：td 内再包 <span><table><tr><td>文本</td></tr></table></span>
  布局嵌套，需要「嵌套回流」模式——嵌套 td 的文本回流到所属的直接 cell

正则切 <tr> 在两种结构下都会重复计数，必须按 DOM 层级处理。零第三方依赖。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser


class _Row:
    __slots__ = ("cells", "attrs")

    def __init__(self, attrs: dict[str, str]):
        self.cells: list[str] = []
        self.attrs = attrs


class TableExtractor(HTMLParser):
    """mode='direct'：每个 td 归属最近开启的 tr（含嵌套表格内的行）。

    mode='nested'：只有未被任何直接 cell 包裹的 td 才开新单元格；
    嵌套 td 的文本回流到所属直接 cell（用于 cell 内布局嵌套的账单）。
    """

    def __init__(self, mode: str = "direct") -> None:
        super().__init__(convert_charrefs=True)
        if mode not in ("direct", "nested"):
            raise ValueError(f"未知模式：{mode}")
        self.mode = mode
        self.rows: list[_Row] = []
        self._row_stack: list[_Row] = []
        self._td_depth: dict[int, int] = {}   # id(row) -> 行内未闭合 td 计数
        self._cell_stack: list[tuple[_Row, int] | None] = []  # nested 模式归属栈
        self._skip_depth = 0

    # -- 标签处理 ----------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if self._skip_depth:
            if tag in ("script", "style"):
                self._skip_depth += 1
            return
        if tag in ("script", "style"):
            self._skip_depth = 1
            return
        if tag == "tr":
            row = _Row(dict(attrs))
            self.rows.append(row)
            self._row_stack.append(row)
            self._td_depth[id(row)] = 0
        elif tag == "td":
            if self.mode == "direct":
                if self._row_stack:
                    row = self._row_stack[-1]
                    row.cells.append("")
                    self._td_depth[id(row)] += 1
            else:  # nested
                if not self._cell_stack:
                    if self._row_stack:
                        row = self._row_stack[-1]
                        row.cells.append("")
                        self._cell_stack.append((row, len(row.cells) - 1))
                    else:
                        self._cell_stack.append(None)  # tr 外畸形 td 占位
                else:
                    self._cell_stack.append(self._cell_stack[-1])
        elif tag == "table" and self.mode == "direct":
            # 直接模式：嵌套表格边界哨兵，防止内层 td 计入外层行
            if self._row_stack:
                row = self._row_stack[-1]
                self._td_depth[id(row)] += 1000

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag in ("script", "style"):
                self._skip_depth -= 1
            return
        if tag == "td":
            if self.mode == "direct":
                if self._row_stack:
                    row = self._row_stack[-1]
                    cur = self._td_depth.get(id(row), 0)
                    if cur > 0:
                        self._td_depth[id(row)] = cur - 1 if cur < 1000 else 999
            else:  # nested
                if self._cell_stack:
                    self._cell_stack.pop()
        elif tag == "tr":
            if self._row_stack:
                row = self._row_stack.pop()
                self._td_depth.pop(id(row), None)
                if self.mode == "nested":
                    while self._cell_stack and self._cell_stack[-1] and self._cell_stack[-1][0] is row:
                        self._cell_stack.pop()
        elif tag == "table" and self.mode == "direct":
            if self._row_stack:
                row = self._row_stack[-1]
                cur = self._td_depth.get(id(row), 0)
                if cur >= 1000:
                    self._td_depth[id(row)] = cur - 1000

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self.mode == "direct":
            if self._row_stack and self._row_stack[-1].cells:
                self._row_stack[-1].cells[-1] += data
        else:  # nested
            if self._cell_stack:
                entry = self._cell_stack[-1]
                if entry:
                    row, idx = entry
                    if row.cells:
                        row.cells[idx] += data

    # -- 结果 --------------------------------------------------------------
    def rows_as_text(self) -> list[list[str]]:
        return [[_norm_cell(c) for c in row.cells] for row in self.rows]


def _norm_cell(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_rows(html: str, mode: str = "direct") -> list[list[str]]:
    """HTML → 行文本矩阵。mode 见 TableExtractor。"""
    parser = TableExtractor(mode=mode)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — 银行 HTML 不规范，解析中断按已有行处理
        pass
    return parser.rows_as_text()


_MONEY_CLEAN = re.compile(r"[¥￥\s,，]")
_YEN_ENTITY = re.compile(r"&yen;?", re.I)


def parse_money(raw: str | None):
    """'¥ 1,597.53' / '-2,647.31' / '&yen;60,000.00' / 'CNY 12.34' → Decimal。

    无法解析返回 None（调用方区分「空」与「0」）。
    """
    from decimal import Decimal, InvalidOperation

    if raw is None:
        return None
    text = _YEN_ENTITY.sub("", raw)
    text = _MONEY_CLEAN.sub("", text)
    text = re.sub(r"^[A-Z]{3,4}(?=-?[0-9])", "", text.strip())
    text = text.strip().rstrip("元").strip()
    if not text or text in {"-", "+", "--"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None
