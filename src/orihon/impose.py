"""PDF の面付けエンジン。

入力 PDF（アプリが「A7折本プリンター」に印刷したもの）を受け取り、
折本のレイアウトに従って 1 枚の用紙に並べ直した PDF を出力する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import ceil, log
from pathlib import Path
from typing import Literal, Sequence

import pymupdf

from . import layouts, paper
from .layouts import Edge, Layout
from .paper import mm

logger = logging.getLogger(__name__)

Guides = Literal["none", "cut", "fold", "full"]
Orientation = Literal["auto", "portrait", "landscape"]
FillMode = Literal["blank", "repeat"]
Fit = Literal["contain", "stretch"]

# 罫線の色（RGB 0..1）
FOLD_COLOR = (0.65, 0.65, 0.65)
CUT_COLOR = (0.0, 0.0, 0.0)


@dataclass
class ImposeOptions:
    """面付けの設定。"""

    layout: str = layouts.DEFAULT_LAYOUT
    paper: str = paper.DEFAULT_PAPER
    orientation: Orientation = "auto"
    #: 各パネルの内側にとる余白（プリンタの印字不可領域よけ）
    safe_margin_mm: float = 4.0
    guides: Guides = "cut"
    fit: Fit = "contain"
    #: ページ数がレイアウトに足りないときの埋め方
    fill: FillMode = "blank"
    #: 出力する用紙の最大枚数（0 で無制限）
    max_sheets: int = 0
    #: パネルの隅にページ番号を薄く入れる（確認用）
    debug_numbers: bool = False
    fold_color: tuple[float, float, float] = FOLD_COLOR
    cut_color: tuple[float, float, float] = CUT_COLOR
    line_width_pt: float = 0.5
    #: 切り取り線に「切り込み」ラベルを入れる
    cut_label: bool = True

    def resolved_layout(self) -> Layout:
        return layouts.get(self.layout)

    def resolved_paper(self) -> paper.Paper:
        return paper.get(self.paper)


@dataclass
class ImposeResult:
    """面付け結果のサマリ。"""

    output: Path
    sheets: int
    source_pages: int
    placed_pages: int
    layout: str
    paper: str
    landscape: bool
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        o = "横" if self.landscape else "縦"
        lines = [
            f"レイアウト : {self.layout}",
            f"用紙       : {self.paper} {o}",
            f"元ページ数 : {self.source_pages}",
            f"配置ページ : {self.placed_pages}",
            f"出力枚数   : {self.sheets}",
            f"出力先     : {self.output}",
        ]
        lines += [f"注意       : {w}" for w in self.warnings]
        return "\n".join(lines)


def _choose_landscape(layout: Layout, sheet: paper.Paper, src_aspect: float) -> bool:
    """パネルの縦横比が元原稿にいちばん近くなる用紙の向きを選ぶ。"""
    best, best_score = False, None
    for landscape in (False, True):
        w, h = sheet.size_pt(landscape)
        panel_aspect = (w / layout.cols) / (h / layout.rows)
        score = abs(log(panel_aspect) - log(src_aspect))
        if best_score is None or score < best_score - 1e-9:
            best, best_score = landscape, score
    return best


def _panel_rect(
    layout: Layout, row: int, col: int, sheet_w: float, sheet_h: float
) -> pymupdf.Rect:
    cw = sheet_w / layout.cols
    ch = sheet_h / layout.rows
    return pymupdf.Rect(col * cw, row * ch, (col + 1) * cw, (row + 1) * ch)


def _edge_segment(
    layout: Layout, edge: Edge, sheet_w: float, sheet_h: float
) -> tuple[pymupdf.Point, pymupdf.Point]:
    cw = sheet_w / layout.cols
    ch = sheet_h / layout.rows
    if edge.orientation == "v":
        x = (edge.col + 1) * cw
        return pymupdf.Point(x, edge.row * ch), pymupdf.Point(x, (edge.row + 1) * ch)
    y = (edge.row + 1) * ch
    return pymupdf.Point(edge.col * cw, y), pymupdf.Point((edge.col + 1) * cw, y)


def _insert_label(page: pymupdf.Page, point: pymupdf.Point, text: str, size: float,
                  color: tuple[float, float, float]) -> None:
    """日本語ラベルを入れる。

    ``show_pdf_page`` を済ませたページに CJK 組み込みフォントで直接
    ``insert_text`` すると、フォントリソース名が原稿側と衝突して文字化けする。
    そこで別ドキュメントにラベルを描いてから等倍で貼り込む。
    CJK フォントが使えない環境では Helvetica の英語ラベルにフォールバックする。
    """
    width = size * (len(text) + 0.5)
    height = size * 1.4
    stamp = pymupdf.open()
    try:
        label_page = stamp.new_page(width=width, height=height)
        try:
            label_page.insert_text(
                pymupdf.Point(0, size), text, fontname="japan", fontsize=size, color=color
            )
        except Exception:  # pragma: no cover - フォント環境依存
            label_page.insert_text(
                pymupdf.Point(0, size), "CUT", fontname="helv", fontsize=size, color=color
            )
        rect = pymupdf.Rect(point.x, point.y - size, point.x + width, point.y - size + height)
        page.show_pdf_page(rect, stamp, 0)
    finally:
        stamp.close()


def _draw_guides(
    page: pymupdf.Page, layout: Layout, opts: ImposeOptions, sheet_w: float, sheet_h: float
) -> None:
    if opts.guides == "none":
        return

    folds = layout.fold_edges()
    cuts = layout.cut_edges()

    if opts.guides in ("fold", "full"):
        for edge in folds:
            p1, p2 = _edge_segment(layout, edge, sheet_w, sheet_h)
            page.draw_line(p1, p2, color=opts.fold_color,
                           width=opts.line_width_pt, dashes="[3 3] 0")

    if opts.guides in ("cut", "full"):
        for edge in cuts:
            p1, p2 = _edge_segment(layout, edge, sheet_w, sheet_h)
            page.draw_line(p1, p2, color=opts.cut_color, width=opts.line_width_pt)

    if opts.guides == "cut" and folds:
        # 折り線は用紙のフチに短いトンボだけ出して、絵柄を邪魔しない
        tick = mm(4.0)
        for edge in folds:
            p1, p2 = _edge_segment(layout, edge, sheet_w, sheet_h)
            if edge.orientation == "v":
                if p1.y <= 0.01:
                    page.draw_line(pymupdf.Point(p1.x, 0), pymupdf.Point(p1.x, tick),
                                   color=opts.fold_color, width=opts.line_width_pt)
                if p2.y >= sheet_h - 0.01:
                    page.draw_line(pymupdf.Point(p2.x, sheet_h - tick),
                                   pymupdf.Point(p2.x, sheet_h),
                                   color=opts.fold_color, width=opts.line_width_pt)
            else:
                if p1.x <= 0.01:
                    page.draw_line(pymupdf.Point(0, p1.y), pymupdf.Point(tick, p1.y),
                                   color=opts.fold_color, width=opts.line_width_pt)
                if p2.x >= sheet_w - 0.01:
                    page.draw_line(pymupdf.Point(sheet_w - tick, p2.y),
                                   pymupdf.Point(sheet_w, p2.y),
                                   color=opts.fold_color, width=opts.line_width_pt)

    if opts.cut_label and cuts and opts.guides in ("cut", "full"):
        first = min(cuts, key=lambda e: (e.row, e.col, e.orientation))
        p1, _ = _edge_segment(layout, first, sheet_w, sheet_h)
        if first.orientation == "h":
            point = pymupdf.Point(p1.x + mm(1.5), p1.y - mm(1.5))
        else:
            point = pymupdf.Point(p1.x + mm(1.5), p1.y + mm(4.0))
        _insert_label(page, point, "切り込み", 6.0, opts.cut_color)


def _source_indices(
    src_pages: int, per_sheet: int, opts: ImposeOptions
) -> tuple[int, bool]:
    """出力枚数と、打ち切りが起きたかどうかを返す。"""
    if src_pages == 0:
        return 0, False
    sheets = max(1, ceil(src_pages / per_sheet))
    truncated = False
    if opts.max_sheets and sheets > opts.max_sheets:
        sheets = opts.max_sheets
        truncated = True
    return sheets, truncated


def impose_document(
    src: pymupdf.Document, opts: ImposeOptions | None = None
) -> tuple[pymupdf.Document, ImposeResult]:
    """開いてある PDF を面付けして、新しい ``Document`` を返す。"""
    opts = opts or ImposeOptions()
    layout = opts.resolved_layout()
    sheet = opts.resolved_paper()

    src_pages = src.page_count
    if src_pages == 0:
        raise ValueError("入力 PDF にページがありません")

    first = src.load_page(0)
    src_rect = first.rect
    src_aspect = (src_rect.width / src_rect.height) if src_rect.height else 1.0

    if opts.orientation == "auto":
        landscape = _choose_landscape(layout, sheet, src_aspect)
    else:
        landscape = opts.orientation == "landscape"

    sheet_w, sheet_h = sheet.size_pt(landscape)
    per_sheet = layout.page_count
    sheets, truncated = _source_indices(src_pages, per_sheet, opts)

    out = pymupdf.open()
    margin = mm(max(0.0, opts.safe_margin_mm))
    placed = 0
    warnings: list[str] = []

    for s in range(sheets):
        page = out.new_page(width=sheet_w, height=sheet_h)
        for row, col, page_no, rotation in layout.cells():
            slot = s * per_sheet + (page_no - 1)
            if slot >= src_pages:
                if opts.fill == "repeat":
                    slot %= src_pages
                else:
                    continue  # 白紙のまま
            rect = _panel_rect(layout, row, col, sheet_w, sheet_h)
            target = rect + (margin, margin, -margin, -margin)
            if target.is_empty or target.width <= 0 or target.height <= 0:
                raise ValueError(
                    f"safe_margin_mm={opts.safe_margin_mm} が大きすぎて"
                    f"パネル（{paper.pt_to_mm(rect.width):.1f}×"
                    f"{paper.pt_to_mm(rect.height):.1f}mm）に収まりません"
                )
            page.show_pdf_page(
                target,
                src,
                slot,
                rotate=rotation % 360,
                keep_proportion=(opts.fit == "contain"),
            )
            placed += 1
            if opts.debug_numbers:
                page.insert_text(
                    pymupdf.Point(rect.x0 + mm(2), rect.y0 + mm(4)),
                    f"p{page_no}",
                    fontname="helv",
                    fontsize=7,
                    color=(0.85, 0.2, 0.2),
                )
        _draw_guides(page, layout, opts, sheet_w, sheet_h)

    if truncated:
        warnings.append(
            f"max_sheets={opts.max_sheets} のため {sheets * per_sheet} ページ目までで打ち切りました"
        )
    remainder = src_pages % per_sheet
    if layout.kind == "foldbook" and remainder and opts.fill == "blank":
        warnings.append(
            f"最後の 1 枚は {per_sheet - remainder} ページ分が白紙になります"
            f"（{per_sheet} の倍数ページにすると無駄がありません）"
        )

    result = ImposeResult(
        output=Path(),
        sheets=sheets,
        source_pages=src_pages,
        placed_pages=placed,
        layout=layout.name,
        paper=sheet.name,
        landscape=landscape,
        truncated=truncated,
        warnings=warnings,
    )
    return out, result


def impose_pdf(
    src_path: str | Path, dst_path: str | Path, opts: ImposeOptions | None = None
) -> ImposeResult:
    """PDF ファイルを面付けしてファイルに書き出す。"""
    src_path = Path(src_path)
    dst_path = Path(dst_path)
    with pymupdf.open(src_path) as src:
        out, result = impose_document(src, opts)
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            out.save(str(dst_path), garbage=3, deflate=True)
        finally:
            out.close()
    result.output = dst_path
    logger.info("imposed %s -> %s (%d sheets)", src_path.name, dst_path.name, result.sheets)
    return result


# ----------------------------------------------------------------------
# テスト用のサンプル原稿づくり
# ----------------------------------------------------------------------
def make_test_document(
    pages: int = 8, size: str = "A7", title: str = "折本テスト"
) -> pymupdf.Document:
    """1,2,3... と大きく番号を振ったテスト用 PDF を作る。"""
    sheet = paper.get(size)
    w, h = sheet.size_pt(False)
    doc = pymupdf.open()
    for i in range(1, pages + 1):
        page = doc.new_page(width=w, height=h)
        page.draw_rect(
            pymupdf.Rect(mm(3), mm(3), w - mm(3), h - mm(3)),
            color=(0.75, 0.75, 0.75),
            width=0.7,
        )
        number = str(i)
        fontsize = min(w, h) * 0.45
        tw = pymupdf.get_text_length(number, fontname="helv", fontsize=fontsize)
        page.insert_text(
            pymupdf.Point((w - tw) / 2, h / 2 + fontsize * 0.35),
            number,
            fontname="helv",
            fontsize=fontsize,
            color=(0.15, 0.15, 0.15),
        )
        # 天地が分かるように上辺だけ帯を引く
        page.draw_rect(
            pymupdf.Rect(mm(3), mm(3), w - mm(3), mm(8)),
            color=None,
            fill=(0.25, 0.45, 0.85),
        )
        try:
            page.insert_text(
                pymupdf.Point(mm(5), mm(14)), f"{title} {i}/{pages}",
                fontname="japan", fontsize=6, color=(0.3, 0.3, 0.3),
            )
        except Exception:  # pragma: no cover - フォント環境依存
            pass
    return doc


def write_test_pdf(
    path: str | Path, pages: int = 8, size: str = "A7"
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = make_test_document(pages=pages, size=size)
    try:
        doc.save(str(path))
    finally:
        doc.close()
    return path


def available_layouts() -> Sequence[Layout]:
    return list(layouts.PRESETS.values())
