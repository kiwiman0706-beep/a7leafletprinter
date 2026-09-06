"""面付けの逆変換 — 折本のシートをスキャンして元のページ順に戻す。

``impose`` がやったことをそのまま巻き戻すだけなので、必要な情報は
レイアウト定義（どのマスに何ページ目がどの向きで入るか）に揃っている。
自前で刷ったシートに限らず、同じ面付けで作られた折本なら戻せる。

スキャンならではの面倒
----------------------
スキャナは紙の周りに白い余白を付けるうえ、原稿の置き方で位置も傾きも
ずれる。そのまま格子で切ると 1 コマずつずれた絵になってしまうので、
まず**印刷されている範囲**を見つけてから、その中を格子で割る。

傾きの補正まではしていない。数度以上傾いているようなら、スキャナ側の
自動補正を使うか、取り込み直したほうが早い。``--preview`` で切り分けを
確かめてから本番を流すのがおすすめ。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import log
from pathlib import Path
from typing import Literal

import pymupdf

from . import layouts, paper
from .layouts import Layout
from .paper import mm

logger = logging.getLogger(__name__)

SheetRotate = Literal["auto", 0, 90, 180, 270]
CropMode = Literal["auto", "always", "never"]

#: 紙の範囲を探すときの描画解像度。細かくしても精度は上がらず遅くなるだけ
ANALYSIS_DPI = 100


@dataclass
class UnimposeOptions:
    """逆面付けの設定。"""

    layout: str = layouts.DEFAULT_LAYOUT
    #: 出力 1 ページの大きさの基準。空ならレイアウトと用紙から求める
    paper: str = paper.DEFAULT_PAPER
    #: スキャンした紙の向き。"auto" は縦横比から 90 度だけ判定する
    sheet_rotate: SheetRotate = "auto"
    #: 紙の位置の決め方。
    #:   auto   … 取り込み結果が既に用紙ちょうどなら、そのまま使う（ScanSnap など）。
    #:            そうでなければインクの範囲から探す
    #:   always … 必ずインクの範囲から探す
    #:   never  … 紙面全体をそのまま使う
    crop: CropMode = "auto"
    #: これより暗い点を「インクがある」とみなす（0-255）
    ink_threshold: int = 235
    #: 1 行（列）のうちこの割合以上にインクがあれば、余白ではないと判断する
    ink_ratio: float = 0.004
    #: 見つけた範囲の外側にこれだけ余裕を持たせる
    crop_padding_mm: float = 0.0
    #: 見つけた範囲を、レイアウトが期待する縦横比に合わせて広げる
    fit_aspect: bool = True
    #: 取り込み結果の縦横比がこの割合以内で用紙と一致すれば、切り出しは不要とみなす
    already_trimmed_tolerance: float = 0.03
    #: 出力するすべてのページに追加でかける回転（面付け時に自動回転した場合など）
    page_rotate: int = 0
    #: 処理するシートの最大枚数（0 で無制限）
    max_sheets: int = 0

    def resolved_layout(self) -> Layout:
        return layouts.get(self.layout)

    def resolved_paper(self) -> paper.Paper:
        return paper.get(self.paper)


@dataclass
class UnimposeResult:
    """逆面付けの結果。"""

    output: Path
    sheets: int
    pages: int
    layout: str
    sheet_rotate: int
    cropped: bool = False
    coverage: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [
            f"レイアウト   : {self.layout}",
            f"シートの向き : {self.sheet_rotate} 度回転して読み取り",
            f"紙の検出     : {'した' if self.cropped else 'しない（全面を使用）'}"
            + (f"（紙面の {self.coverage * 100:.0f}%）" if self.cropped else ""),
            f"シート枚数   : {self.sheets}",
            f"復元ページ数 : {self.pages}",
            f"出力先       : {self.output}",
        ]
        lines += [f"注意         : {w}" for w in self.warnings]
        return "\n".join(lines)


# ----------------------------------------------------------------------
# 紙の範囲を見つける
# ----------------------------------------------------------------------
def detect_content_rect(
    page: pymupdf.Page,
    threshold: int = 235,
    ink_ratio: float = 0.004,
    dpi: int = ANALYSIS_DPI,
    min_ink_pixels: int | None = None,
) -> pymupdf.Rect | None:
    """印刷されている範囲を返す。何も見つからなければ None。

    ``detect_uniform_bands``（面付け側）が「まったく同じ色が並ぶ帯」を
    見るのに対し、こちらは**しきい値より暗い点の数**で判断する。
    スキャン画像の白地は完全な白ではなく、わずかに濁っているため。

    ``min_ink_pixels`` を渡すと、割合ではなく実数で判定する。
    トンボのような細い線は解析用の縮小画像では数ピクセルしか残らず、
    割合で見るとノイズとして落ちてしまうため、そのときに使う。
    """
    try:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    except Exception as exc:  # pragma: no cover - 壊れたページなど
        logger.warning("ページを描画できませんでした: %s", exc)
        return None

    width, height, stride = pix.width, pix.height, pix.stride
    if width < 8 or height < 8:
        return None
    buf = pix.samples

    row_ink = [0] * height
    col_ink = [0] * width
    for y in range(height):
        base = y * stride
        row = buf[base : base + width]
        count = 0
        for x, value in enumerate(row):
            if value < threshold:
                count += 1
                col_ink[x] += 1
        row_ink[y] = count

    if min_ink_pixels is None:
        row_limit = max(1, int(width * ink_ratio))
        col_limit = max(1, int(height * ink_ratio))
    else:
        # 細い線（トンボや罫）を拾いたいときは、割合ではなく実数で見る
        row_limit = col_limit = max(1, min_ink_pixels)

    rows = [y for y, ink in enumerate(row_ink) if ink >= row_limit]
    cols = [x for x, ink in enumerate(col_ink) if ink >= col_limit]
    if not rows or not cols:
        return None

    scale_x = page.rect.width / width
    scale_y = page.rect.height / height
    return pymupdf.Rect(
        page.rect.x0 + cols[0] * scale_x,
        page.rect.y0 + rows[0] * scale_y,
        page.rect.x0 + (cols[-1] + 1) * scale_x,
        page.rect.y0 + (rows[-1] + 1) * scale_y,
    )


def resolve_orientation(content: pymupdf.Rect, layout: Layout,
                        sheet: paper.Paper) -> tuple[int, bool]:
    """スキャンを何度回して読むか、元のシートは横置きだったかを決める。

    手がかりはパネルの形。A 判の紙を格子に割った 1 コマは、やはり
    A 判に近い比になる（A4 横を 4 列 2 段なら A7 縦）。そこで、回さずに
    読んだ場合と 90 度回して読んだ場合それぞれについてパネルの比を出し、
    用紙そのものの比に近い方を採る。

    正方形の格子（2 列 2 段など）では、どちらに読んでもパネルの形が
    同じになるので判断できない。その場合は「回さない」を選ぶ。
    上下逆（180 度）も見た目が変わらないため判断できない。
    どちらも ``--preview`` で確かめて ``--sheet-rotate`` で直してもらう。

    戻り値は ``(回す角度, 元のシートが横置きだったか)``。
    """
    if content.width <= 0 or content.height <= 0:
        return 0, True

    scanned = content.width / content.height
    portrait_w, portrait_h = sheet.size_pt(False)
    ideal = abs(log(portrait_w / portrait_h))   # A 判なら log(1/√2)

    best: tuple[float, int, bool] | None = None
    for rotation in (0, 90):
        # 回して読むということは、元の紙の縦横比は逆だったということ
        original = scanned if rotation == 0 else 1.0 / scanned
        panel = original * layout.rows / layout.cols
        score = abs(abs(log(panel)) - ideal)
        # 差が十分小さければ「回さない」を優先する（正方格子は判断できないため）
        if best is None or score < best[0] - 1e-6:
            best = (score, rotation, original > 1.0)
    assert best is not None
    return best[1], best[2]


def choose_sheet_rotation(content: pymupdf.Rect, layout: Layout,
                          sheet: paper.Paper) -> int:
    """スキャンした紙を何度回して読むべきか。"""
    return resolve_orientation(content, layout, sheet)[0]


def fit_to_aspect(rect: pymupdf.Rect, aspect: float,
                  bounds: pymupdf.Rect) -> tuple[pymupdf.Rect, bool]:
    """見つけた範囲を、あるべき縦横比になるまで左右対称に広げる。

    絵柄の端に余白があると、インクの範囲は紙より内側に出てしまう。
    面付けはパネルの内側に同じ幅の余白をとるので、足りない分は
    上下・左右とも同じだけのはず。だから中心を保ったまま広げれば、
    元の紙の大きさに戻せる。狭める方向には動かさない（絵柄を切らないため）。

    ``bounds`` からはみ出す場合は切り詰め、2 つ目の戻り値を True にする。
    """
    if rect.width <= 0 or rect.height <= 0 or aspect <= 0:
        return rect, False

    width, height = rect.width, rect.height
    if width / height < aspect:
        width = height * aspect
    else:
        height = width / aspect

    cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    grown = pymupdf.Rect(cx - width / 2, cy - height / 2,
                         cx + width / 2, cy + height / 2)
    clipped = grown & bounds
    return clipped, not grown.is_empty and (
        abs(clipped.width - grown.width) > 0.5 or abs(clipped.height - grown.height) > 0.5
    )


def panel_size(layout: Layout, sheet: paper.Paper, landscape: bool) -> tuple[float, float]:
    """元のシートを格子に割った 1 コマの寸法＝復元後 1 ページの大きさ。"""
    width, height = sheet.size_pt(landscape)
    return width / layout.cols, height / layout.rows


def resolve_sheet(page: pymupdf.Page, layout: Layout, sheet: paper.Paper,
                  opts: "UnimposeOptions") -> tuple[pymupdf.Rect, int, bool, list[str]]:
    """1 枚のスキャンについて、シートの範囲・読み取る向き・元の用紙の向きを決める。

    本番と ``--preview`` で同じ結果になるよう、判断はここに集約している。

    ScanSnap のような書類スキャナは紙の端を機械的に見つけて、用紙ちょうどに
    切って出してくれる。その場合は探す必要がないどころか、探してはいけない。
    手書きのメモのようにインクが紙の一部にしかないものだと、文字のある範囲を
    紙と取り違えてしまうからだ。そこで ``crop="auto"`` では、取り込み結果の
    縦横比が用紙と一致していれば、そのまま使う。
    """
    notes: list[str] = []
    page_rect = page.rect

    def orientation_of(rect: pymupdf.Rect) -> tuple[int, bool]:
        if opts.sheet_rotate == "auto":
            return resolve_orientation(rect, layout, sheet)
        rotation = int(opts.sheet_rotate) % 360
        scanned = rect.width / rect.height if rect.height else 1.0
        original = scanned if rotation % 180 == 0 else 1.0 / scanned
        return rotation, original > 1.0

    def expected_aspect(rotation: int, landscape: bool) -> float:
        width, height = sheet.size_pt(landscape)
        aspect = width / height
        return (1.0 / aspect) if rotation % 180 else aspect

    # すでに用紙ちょうどに切られていないか
    rotation, landscape = orientation_of(page_rect)
    if opts.crop != "always" and page_rect.height:
        want = expected_aspect(rotation, landscape)
        got = page_rect.width / page_rect.height
        if opts.crop == "never" or abs(got - want) / want <= opts.already_trimmed_tolerance:
            return page_rect, rotation, landscape, notes

    # インクの範囲から紙を探す
    found = detect_content_rect(page, opts.ink_threshold, opts.ink_ratio)
    if found is None:
        notes.append("印刷されている範囲を見つけられず、紙全体を使いました")
        return page_rect, rotation, landscape, notes

    # 見つけた範囲の比が用紙とかけ離れているなら、細い線を拾えていない
    # 可能性がある。しきい値を実数に切り替えてもう一度だけ探す。
    # （縦横比あわせは「足りない分は上下・左右とも同じ」を前提にしているので、
    #   片方の軸だけ大きく外していると直しきれない）
    guess_rotation, guess_landscape = orientation_of(found)
    want = expected_aspect(guess_rotation, guess_landscape)
    if found.height and abs(found.width / found.height - want) / want > 0.02:
        retry = detect_content_rect(page, opts.ink_threshold, opts.ink_ratio,
                                    min_ink_pixels=2)
        if retry is not None and retry.height:
            if abs(retry.width / retry.height - want) < abs(found.width / found.height - want):
                found = retry

    padding = mm(opts.crop_padding_mm)
    content = (found + (-padding, -padding, padding, padding)) & page_rect
    rotation, landscape = orientation_of(content)

    if opts.fit_aspect:
        content, clipped = fit_to_aspect(content, expected_aspect(rotation, landscape), page_rect)
        if clipped:
            notes.append(
                "シートが紙面からはみ出しています。取り込み範囲を広げるか、"
                "--no-fit-aspect を試してください"
            )

    if content.width * content.height < page_rect.width * page_rect.height * 0.25:
        notes.append(
            "紙とみなした範囲が小さすぎます。書き込みが少ない原稿では"
            " --crop never（紙面全体を使う）の方が確実です"
        )
    return content, rotation, landscape, notes


# ----------------------------------------------------------------------
# 逆面付け
# ----------------------------------------------------------------------
def _panel_clip(content: pymupdf.Rect, layout: Layout, row: int, col: int,
                rotation: int) -> pymupdf.Rect:
    """シートを回して見たときの (row, col) が、元の紙のどこに当たるか。"""
    cols, rows = layout.cols, layout.rows
    if rotation % 180:
        cols, rows = rows, cols

    if rotation % 360 == 90:
        # 紙を時計回りに 90 度回して見ている＝元の紙では左下から数える
        src_row, src_col = layout.cols - 1 - col, row
    elif rotation % 360 == 270:
        src_row, src_col = col, layout.rows - 1 - row
    elif rotation % 360 == 180:
        src_row, src_col = layout.rows - 1 - row, layout.cols - 1 - col
    else:
        src_row, src_col = row, col

    cell_w = content.width / cols
    cell_h = content.height / rows
    return pymupdf.Rect(
        content.x0 + src_col * cell_w,
        content.y0 + src_row * cell_h,
        content.x0 + (src_col + 1) * cell_w,
        content.y0 + (src_row + 1) * cell_h,
    )


def unimpose_document(
    src: pymupdf.Document, opts: UnimposeOptions | None = None
) -> tuple[pymupdf.Document, UnimposeResult]:
    """スキャンした折本のシートを、元のページ順に並べ直す。"""
    opts = opts or UnimposeOptions()
    layout = opts.resolved_layout()
    sheet = opts.resolved_paper()

    if src.page_count == 0:
        raise ValueError("入力にページがありません")

    sheets = src.page_count
    truncated = False
    if opts.max_sheets and sheets > opts.max_sheets:
        sheets = opts.max_sheets
        truncated = True

    out = pymupdf.open()
    warnings: list[str] = []
    per_sheet = layout.page_count

    cropped_any = False
    coverage_sum = 0.0
    rotation = 0

    for index in range(sheets):
        page = src.load_page(index)
        content, rotation, landscape, notes = resolve_sheet(page, layout, sheet, opts)
        warnings += [f"{index + 1} 枚目: {note}" for note in notes]
        page_w, page_h = panel_size(layout, sheet, landscape)
        if content != page.rect:
            cropped_any = True
            coverage_sum += (content.width * content.height) / (
                page.rect.width * page.rect.height
            )

        # 出力ページの向きは、シートを回した結果に合わせる
        out_w, out_h = (page_h, page_w) if opts.page_rotate % 180 else (page_w, page_h)

        # はじめからページ番号の順に作る（あとで並べ替える必要がない）
        for page_no in range(1, per_sheet + 1):
            row, col = layout.position_of(page_no)
            cell_rotation = layout.rotations[row][col]
            clip = _panel_clip(content, layout, row, col, rotation)
            if clip.is_empty or clip.width <= 0 or clip.height <= 0:
                warnings.append(f"{index + 1} 枚目のページ {page_no} を切り出せませんでした")
                continue
            target = out.new_page(width=out_w, height=out_h)
            # 面付けでかけた回転を打ち消し、さらにシートの向きの分を戻す
            angle = (-cell_rotation - rotation + opts.page_rotate) % 360
            target.show_pdf_page(
                pymupdf.Rect(0, 0, out_w, out_h), src, index,
                clip=clip, rotate=angle, keep_proportion=True,
            )

    if truncated:
        warnings.append(f"max_sheets={opts.max_sheets} のため {sheets} 枚目までにしました")

    result = UnimposeResult(
        output=Path(),
        sheets=sheets,
        pages=out.page_count,
        layout=layout.name,
        sheet_rotate=rotation,
        cropped=cropped_any,
        coverage=(coverage_sum / sheets) if cropped_any and sheets else 0.0,
        warnings=warnings,
    )
    return out, result


def unimpose_pdf(
    src_path: str | Path, dst_path: str | Path, opts: UnimposeOptions | None = None
) -> UnimposeResult:
    """スキャンした PDF／画像を、元のページ順の PDF に戻す。"""
    src_path = Path(src_path)
    dst_path = Path(dst_path)
    with open_scan(src_path) as src:
        out, result = unimpose_document(src, opts)
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            out.save(str(dst_path), garbage=3, deflate=True)
        finally:
            out.close()
    result.output = dst_path
    logger.info("unimposed %s -> %s (%d pages)", src_path.name, dst_path.name, result.pages)
    return result


def open_scan(path: str | Path) -> pymupdf.Document:
    """PDF でも画像でも開けるようにする。

    スキャナの出力は PDF とは限らず、JPEG や PNG のこともある。
    """
    path = Path(path)
    if path.suffix.lower() in (".pdf",):
        return pymupdf.open(stream=path.read_bytes(), filetype="pdf")
    # 画像は 1 ページの PDF に包む
    image = pymupdf.open(str(path))
    pdf_bytes = image.convert_to_pdf()
    image.close()
    return pymupdf.open(stream=pdf_bytes, filetype="pdf")


# ----------------------------------------------------------------------
# 切り分けの確認用
# ----------------------------------------------------------------------
def preview_pdf(
    src_path: str | Path, dst_path: str | Path, opts: UnimposeOptions | None = None
) -> Path:
    """どこをどのページとして切り出すつもりかを、元のスキャンに重ねて描く。"""
    opts = opts or UnimposeOptions()
    layout = opts.resolved_layout()
    sheet = opts.resolved_paper()
    src_path, dst_path = Path(src_path), Path(dst_path)

    with open_scan(src_path) as src:
        out = pymupdf.open()
        limit = opts.max_sheets or src.page_count
        for index in range(min(src.page_count, limit)):
            page = src.load_page(index)
            content, rotation, _landscape, _notes = resolve_sheet(page, layout, sheet, opts)
            target = out.new_page(width=page.rect.width, height=page.rect.height)
            target.show_pdf_page(target.rect, src, index)
            target.draw_rect(content, color=(0.1, 0.5, 0.9), width=1.5)

            for row, col, page_no, _rot in layout.cells():
                clip = _panel_clip(content, layout, row, col, rotation)
                target.draw_rect(clip, color=(0.9, 0.3, 0.2), width=0.8)
                label = pymupdf.Point(clip.x0 + mm(3), clip.y0 + mm(8))
                target.insert_text(label, str(page_no), fontname="helv",
                                   fontsize=22, color=(0.9, 0.3, 0.2))
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            out.save(str(dst_path), garbage=3, deflate=True)
        finally:
            out.close()
    return dst_path
