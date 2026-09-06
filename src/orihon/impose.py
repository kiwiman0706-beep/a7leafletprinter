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
    #: 原稿とパネルの縦横が食い違うとき、パネル内で 90 度回して余白を減らす
    auto_rotate: bool = True
    #: 原稿の上下左右にある「単色の帯」を切り落としてから配置する
    #: （PowerPoint を用紙に合わせて印刷したときの余白対策）
    trim: bool = False
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
    #: 原稿がパネル面積のどれだけを埋めたか（0.0〜1.0 の平均）
    coverage: float = 0.0
    #: パネル内で 90 度回したページ数
    rotated_pages: int = 0
    #: 周囲の単色の帯を切り落としたページ数
    trimmed_pages: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        o = "横" if self.landscape else "縦"
        lines = [
            f"レイアウト : {self.layout}",
            f"用紙       : {self.paper} {o}",
            f"元ページ数 : {self.source_pages}",
            f"配置ページ : {self.placed_pages}",
            f"用紙の使用率: {self.coverage * 100:.0f}%"
            + (f"（うち {self.rotated_pages} ページを90度回転）" if self.rotated_pages else ""),
            f"出力枚数   : {self.sheets}",
            f"出力先     : {self.output}",
        ]
        lines += [f"注意       : {w}" for w in self.warnings]
        return "\n".join(lines)


def _choose_landscape(
    layout: Layout, sheet: paper.Paper, src_aspect: float, auto_rotate: bool = True
) -> bool:
    """パネルの縦横比が元原稿にいちばん近くなる用紙の向きを選ぶ。

    パネル内で 90 度回すことを許す場合は、原稿を寝かせた縦横比も候補に入れる。
    """
    candidates = [src_aspect] + ([1.0 / src_aspect] if auto_rotate and src_aspect else [])
    best, best_score = False, None
    for landscape in (False, True):
        w, h = sheet.size_pt(landscape)
        panel_aspect = (w / layout.cols) / (h / layout.rows)
        score = min(abs(log(panel_aspect) - log(a)) for a in candidates)
        # 正方形の格子（2列2段など）では、どちらの向きでもパネルの形が同じで
        # 差がつかない。そのときはレイアウトが想定する持ち方に合わせる。
        # turn=90（天綴じ）は横長のパネル、turn=0 は縦長のパネルを想定している。
        wants_landscape_panel = layout.turn == 90
        if (panel_aspect > 1.0) == wants_landscape_panel:
            score -= 1e-6
        if best_score is None or score < best_score - 1e-9:
            best, best_score = landscape, score
    return best


@dataclass(frozen=True)
class Bands:
    """ページの上下左右にある「全幅／全高が単色」の帯の割合（0.0〜1.0）。"""

    top: float = 0.0
    bottom: float = 0.0
    left: float = 0.0
    right: float = 0.0

    @property
    def remaining(self) -> float:
        """帯を除いたあとに残る面積の割合。"""
        return max(0.0, 1.0 - self.top - self.bottom) * max(0.0, 1.0 - self.left - self.right)

    @property
    def significant(self) -> bool:
        return self.remaining < 0.85

    def clip(self, rect: pymupdf.Rect) -> pymupdf.Rect:
        return pymupdf.Rect(
            rect.x0 + rect.width * self.left,
            rect.y0 + rect.height * self.top,
            rect.x1 - rect.width * self.right,
            rect.y1 - rect.height * self.bottom,
        )


def detect_uniform_bands(
    page: pymupdf.Page, dpi: int = 48, max_band: float = 0.45
) -> Bands:
    """ページの縁にある単色の帯を測る。

    PowerPoint のスライドを用紙に合わせて印刷すると、上下（または左右）に
    大きな白帯が付く。この帯は「全幅にわたって色が一様な行」が続く範囲として
    見つけられる。1 辺あたり ``max_band`` までしか削らないので、
    ほとんど白紙のページでも中身が消えてしまうことはない。
    """
    try:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    except Exception as exc:  # pragma: no cover - 壊れたページなど
        logger.debug("帯の検出に失敗しました: %s", exc)
        return Bands()
    width, height, stride = pix.width, pix.height, pix.stride
    if width < 4 or height < 4:
        return Bands()
    buf = pix.samples

    def row_uniform(y: int) -> bool:
        start = y * stride
        line = buf[start : start + width]
        return line.count(line[0]) == width

    def col_uniform(x: int) -> bool:
        first = buf[x]
        return all(buf[y * stride + x] == first for y in range(height))

    def count(is_uniform, total: int, reverse: bool) -> int:
        limit = int(total * max_band)
        k = 0
        while k < limit and is_uniform(total - 1 - k if reverse else k):
            k += 1
        return k

    top = count(row_uniform, height, False)
    bottom = count(row_uniform, height, True)
    left = count(col_uniform, width, False)
    right = count(col_uniform, width, True)
    return Bands(top / height, bottom / height, left / width, right / width)


def _fit_coverage(panel_w: float, panel_h: float, src_w: float, src_h: float) -> float:
    """縦横比を保って収めたとき、原稿がパネル面積の何割を埋めるか。"""
    if min(panel_w, panel_h, src_w, src_h) <= 0:
        return 0.0
    scale = min(panel_w / src_w, panel_h / src_h)
    return (src_w * scale) * (src_h * scale) / (panel_w * panel_h)


def _rotated_size(width: float, height: float, rotation: int) -> tuple[float, float]:
    return (height, width) if rotation % 180 else (width, height)


def _best_rotation(
    panel_w: float, panel_h: float, src_w: float, src_h: float, base: int, auto: bool
) -> tuple[int, float, bool]:
    """パネルに対していちばん無駄の少ない回転角を選ぶ。

    ``(回転角, 占有率, 90度回したか)`` を返す。差がごくわずかなときは
    回さない（ほぼ正方形の原稿がページごとにバラバラの向きになるのを防ぐ）。
    """
    bw, bh = _rotated_size(src_w, src_h, base)
    base_cov = _fit_coverage(panel_w, panel_h, bw, bh)
    if not auto:
        return base % 360, base_cov, False
    turned = (base + 90) % 360
    tw, th = _rotated_size(src_w, src_h, turned)
    turned_cov = _fit_coverage(panel_w, panel_h, tw, th)
    if turned_cov > base_cov * 1.02:
        return turned, turned_cov, True
    return base % 360, base_cov, False


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
        landscape = _choose_landscape(layout, sheet, src_aspect, opts.auto_rotate)
    else:
        landscape = opts.orientation == "landscape"

    sheet_w, sheet_h = sheet.size_pt(landscape)
    per_sheet = layout.page_count
    sheets, truncated = _source_indices(src_pages, per_sheet, opts)

    out = pymupdf.open()
    margin = mm(max(0.0, opts.safe_margin_mm))
    placed = 0
    rotated = 0
    trimmed = 0
    coverage_sum = 0.0
    warnings: list[str] = []
    band_cache: dict[int, Bands] = {}

    def bands_for(index: int) -> Bands:
        if index not in band_cache:
            band_cache[index] = detect_uniform_bands(src.load_page(index))
        return band_cache[index]

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
            src_page_rect = src.load_page(slot).rect
            clip = None
            if opts.trim:
                bands = bands_for(slot)
                if bands.significant:
                    clip = bands.clip(src_page_rect)
                    src_page_rect = clip
                    trimmed += 1
            angle, coverage, turned = _best_rotation(
                target.width, target.height,
                src_page_rect.width, src_page_rect.height,
                rotation, opts.auto_rotate,
            )
            page.show_pdf_page(
                target,
                src,
                slot,
                rotate=angle,
                keep_proportion=(opts.fit == "contain"),
                clip=clip,
            )
            placed += 1
            rotated += int(turned)
            coverage_sum += coverage if opts.fit == "contain" else 1.0
            if opts.debug_numbers:
                page.insert_text(
                    pymupdf.Point(rect.x0 + mm(2), rect.y0 + mm(4)),
                    f"p{page_no}",
                    fontname="helv",
                    fontsize=7,
                    color=(0.85, 0.2, 0.2),
                )
        _draw_guides(page, layout, opts, sheet_w, sheet_h)

    coverage = coverage_sum / placed if placed else 0.0

    if trimmed:
        warnings.append(f"{trimmed} ページの周囲にあった単色の帯を切り落としました")
    elif not opts.trim:
        # 「用紙に合わせて印刷」でできた白帯は、面積だけ見ると気づけない
        first_bands = bands_for(0)
        if first_bands.significant:
            warnings.append(
                f"原稿の周囲に大きな余白（実質 {first_bands.remaining * 100:.0f}%）があります。"
                "アプリ側で用紙に合わせて印刷されたのかもしれません。"
                " --trim を付けると切り落とせます"
            )

    if rotated:
        warnings.append(
            f"原稿が横長（またはパネルと向きちがい）だったため、{rotated} ページを"
            "パネル内で 90 度回して配置しました（読むときは冊子を回してください）"
        )
        if layout.sibling:
            sibling = layouts.get(layout.sibling)
            warnings.append(
                f"回さずに読みたい場合は --layout {sibling.name} をお試しください"
                f"（{sibling.title}）"
            )
    elif coverage and coverage < 0.55 and layout.sibling:
        sibling = layouts.get(layout.sibling)
        warnings.append(
            f"用紙の使用率が {coverage * 100:.0f}% と低めです。"
            f"--layout {sibling.name}（{sibling.title}）のほうが無駄が少ないかもしれません"
        )

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
        coverage=coverage,
        rotated_pages=rotated,
        trimmed_pages=trimmed,
        truncated=truncated,
        warnings=warnings,
    )
    return out, result


#: これより小さい PDF はメモリに読み込んでから開く（下の open_pdf を参照）
IN_MEMORY_LIMIT = 200 * 1024 * 1024


def open_pdf(path: str | Path) -> pymupdf.Document:
    """PDF を開く。小さいものはメモリに読み込んでから開く。

    Windows では、開いたまま（あるいは開くのに失敗した直後）のファイルを
    リネームも削除もできない。スプールのファイルは処理後に必ず片付けるので、
    ファイルハンドルを握らずに済むこの方法を既定にしている。
    """
    path = Path(path)
    try:
        if path.stat().st_size <= IN_MEMORY_LIMIT:
            return pymupdf.open(stream=path.read_bytes(), filetype="pdf")
    except OSError as exc:
        logger.debug("メモリに読み込めませんでした（ファイルとして開きます）: %s", exc)
    return pymupdf.open(path)


def impose_pdf(
    src_path: str | Path, dst_path: str | Path, opts: ImposeOptions | None = None
) -> ImposeResult:
    """PDF ファイルを面付けしてファイルに書き出す。"""
    src_path = Path(src_path)
    dst_path = Path(dst_path)
    with open_pdf(src_path) as src:
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
