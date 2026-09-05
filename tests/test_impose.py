"""面付けエンジンの検証。"""

import pymupdf
import pytest

from orihon import impose, layouts, paper
from orihon.paper import mm

A4_LANDSCAPE = (mm(297), mm(210))
A4_PORTRAIT = (mm(210), mm(297))


@pytest.fixture()
def src8(tmp_path):
    return impose.write_test_pdf(tmp_path / "src8.pdf", pages=8, size="A7")


def _cell_of(layout, page_rect, point):
    """点がどのパネル (row, col) に入るかを返す。"""
    cw = page_rect.width / layout.cols
    ch = page_rect.height / layout.rows
    return int(point.y // ch), int(point.x // cw)


def _spans(page):
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                yield line, span


def test_output_is_single_a4_landscape_sheet(src8, tmp_path):
    out = tmp_path / "out.pdf"
    result = impose.impose_pdf(src8, out, impose.ImposeOptions(layout="orihon8"))
    assert result.sheets == 1
    assert result.landscape is True
    with pymupdf.open(out) as doc:
        assert doc.page_count == 1
        rect = doc.load_page(0).rect
    assert rect.width == pytest.approx(A4_LANDSCAPE[0], abs=1)
    assert rect.height == pytest.approx(A4_LANDSCAPE[1], abs=1)


def test_orihon4_auto_picks_portrait(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=4, size="A6")
    result = impose.impose_pdf(src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon4"))
    assert result.landscape is False


def test_orientation_can_be_forced(src8, tmp_path):
    result = impose.impose_pdf(
        src8, tmp_path / "o.pdf",
        impose.ImposeOptions(layout="orihon8", orientation="portrait"),
    )
    assert result.landscape is False


def test_every_page_lands_in_the_cell_the_layout_says(src8, tmp_path):
    """各ページ番号が、レイアウトどおりのマスに、正しい向きで入っていること。"""
    layout = layouts.get("orihon8")
    out = tmp_path / "out.pdf"
    impose.impose_pdf(src8, out, impose.ImposeOptions(layout="orihon8", guides="none"))

    with pymupdf.open(out) as doc:
        page = doc.load_page(0)
        rect = page.rect
        found = {}
        for line, span in _spans(page):
            text = span["text"].strip()
            if not text.isdigit():
                continue
            centre = pymupdf.Point(
                (span["bbox"][0] + span["bbox"][2]) / 2,
                (span["bbox"][1] + span["bbox"][3]) / 2,
            )
            found[int(text)] = (_cell_of(layout, rect, centre), tuple(round(v) for v in line["dir"]))

    assert set(found) == set(range(1, 9)), f"見つかった数字: {sorted(found)}"
    for row, col, page_no, rotation in layout.cells():
        cell, direction = found[page_no]
        assert cell == (row, col), f"ページ {page_no} が {cell} にある（期待: {(row, col)}）"
        expected_dir = (1, 0) if rotation % 360 == 0 else (-1, 0)
        assert direction == expected_dir, f"ページ {page_no} の向きが {direction}"


def test_multiple_sheets_for_long_documents(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=17, size="A7")
    result = impose.impose_pdf(src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8"))
    assert result.sheets == 3
    assert result.placed_pages == 17  # 余りは白紙
    assert any("白紙" in w for w in result.warnings)


def test_max_sheets_truncates(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=17, size="A7")
    result = impose.impose_pdf(
        src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8", max_sheets=1)
    )
    assert result.sheets == 1
    assert result.truncated is True


def test_fill_repeat_tiles_a_single_page(tmp_path):
    """1 ページの原稿を 8 面に複製できること（A7 チラシ用途）。"""
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=1, size="A7")
    result = impose.impose_pdf(
        src, tmp_path / "o.pdf", impose.ImposeOptions(layout="nup8", fill="repeat")
    )
    assert result.sheets == 1
    assert result.placed_pages == 8
    with pymupdf.open(result.output) as doc:
        assert doc.load_page(0).get_text().count("1") >= 8


def test_fill_blank_leaves_empty_panels(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=3, size="A7")
    result = impose.impose_pdf(
        src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8", fill="blank")
    )
    assert result.placed_pages == 3


def test_guides_none_draws_nothing_extra(src8, tmp_path):
    a = tmp_path / "none.pdf"
    b = tmp_path / "full.pdf"
    impose.impose_pdf(src8, a, impose.ImposeOptions(layout="orihon8", guides="none"))
    impose.impose_pdf(src8, b, impose.ImposeOptions(layout="orihon8", guides="full"))
    assert a.stat().st_size < b.stat().st_size


def test_cut_label_is_rendered_as_japanese(src8, tmp_path):
    out = tmp_path / "o.pdf"
    impose.impose_pdf(src8, out, impose.ImposeOptions(layout="orihon8", guides="cut"))
    with pymupdf.open(out) as doc:
        assert "切り込み" in doc.load_page(0).get_text()


def test_content_stays_inside_its_panel(src8, tmp_path):
    """余白を指定したら、絵柄がパネルの内側に収まること。"""
    layout = layouts.get("orihon8")
    out = tmp_path / "o.pdf"
    margin = 6.0
    impose.impose_pdf(
        src8, out,
        impose.ImposeOptions(layout="orihon8", guides="none", safe_margin_mm=margin),
    )
    with pymupdf.open(out) as doc:
        page = doc.load_page(0)
        cw = page.rect.width / layout.cols
        ch = page.rect.height / layout.rows
        for _line, span in _spans(page):
            if not span["text"].strip().isdigit():
                continue
            x0, y0, x1, y1 = span["bbox"]
            col, row = int(((x0 + x1) / 2) // cw), int(((y0 + y1) / 2) // ch)
            assert x0 >= col * cw + mm(margin) - 1
            assert x1 <= (col + 1) * cw - mm(margin) + 1
            assert y0 >= row * ch + mm(margin) - 1
            assert y1 <= (row + 1) * ch - mm(margin) + 1


def test_too_large_margin_is_rejected(src8, tmp_path):
    with pytest.raises(ValueError, match="大きすぎて"):
        impose.impose_pdf(
            src8, tmp_path / "o.pdf",
            impose.ImposeOptions(layout="orihon8", safe_margin_mm=60),
        )


def test_empty_pdf_is_rejected():
    with pymupdf.open() as empty:  # ページが 1 枚も無い PDF
        with pytest.raises(ValueError, match="ページがありません"):
            impose.impose_document(empty)


def test_custom_paper_size(src8, tmp_path):
    result = impose.impose_pdf(
        src8, tmp_path / "o.pdf",
        impose.ImposeOptions(layout="orihon8", paper="300x200", orientation="portrait"),
    )
    with pymupdf.open(result.output) as doc:
        rect = doc.load_page(0).rect
    assert rect.width == pytest.approx(mm(300), abs=1)
    assert rect.height == pytest.approx(mm(200), abs=1)


def test_all_presets_impose_without_error(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    for name in layouts.names():
        result = impose.impose_pdf(src, tmp_path / f"{name}.pdf",
                                   impose.ImposeOptions(layout=name))
        assert result.sheets >= 1


def test_unknown_paper_raises():
    with pytest.raises(KeyError):
        paper.get("A99")
