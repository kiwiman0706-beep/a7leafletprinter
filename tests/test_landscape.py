"""横長原稿（スライドなど）の扱いと、用紙ごと 90 度倒したレイアウトの検証。"""

import pymupdf
import pytest

from orihon import impose, layouts
from orihon.layouts import Edge, LayoutError

#: 16:9 のスライド（254 x 142.9mm）と 4:3（254 x 190.5mm）
SLIDE_16_9 = "254x142.9"
SLIDE_4_3 = "254x190.5"


@pytest.fixture()
def slides(tmp_path):
    return impose.write_test_pdf(tmp_path / "slides.pdf", pages=8, size=SLIDE_16_9)


# ----------------------------------------------------------------------
# rotate90 が「同じ紙を 90 度倒しただけ」であること
# ----------------------------------------------------------------------
def _turned_edge(edge: Edge, rows: int) -> Edge:
    """元レイアウトの境界が、90 度倒した後のどの境界になるかを返す。"""
    if edge.orientation == "v":
        return Edge(edge.col, rows - 1 - edge.row, "h")
    return Edge(edge.col, rows - 2 - edge.row, "v")


@pytest.mark.parametrize("base_name", ["orihon8", "orihon4"])
def test_turned_layout_is_the_same_sheet(base_name):
    """折り線・切り込みが、そっくり 90 度回っただけであること。"""
    base = layouts.get(base_name)
    turned = layouts.get(f"{base_name}-landscape")

    assert (turned.rows, turned.cols) == (base.cols, base.rows)
    assert {_turned_edge(e, base.rows) for e in base.cut_edges()} == set(turned.cut_edges())
    assert {_turned_edge(e, base.rows) for e in base.fold_edges()} == set(turned.fold_edges())


def test_turned_layout_keeps_page_order():
    base = layouts.get("orihon8")
    turned = layouts.get("orihon8-landscape")
    for page in range(1, 9):
        r, c = base.position_of(page)
        assert turned.position_of(page) == (c, base.rows - 1 - r)


def test_turned_layout_panels_are_landscape():
    """A4 縦に置いたとき、パネルが横長になること。"""
    turned = layouts.get("orihon8-landscape")
    panel_w = 210 / turned.cols
    panel_h = 297 / turned.rows
    assert panel_w > panel_h
    assert (round(panel_w), round(panel_h)) == (105, 74)  # A7 を横に寝かせた形


def test_cover_is_upright_in_every_preset():
    """表紙（ページ1）はどのレイアウトでも回転 0 度で置かれること。"""
    for layout in layouts.PRESETS.values():
        if layout.kind != "foldbook":
            continue
        r, c = layout.position_of(1)
        assert layout.rotations[r][c] == 0, layout.name


def test_turned_layout_is_top_bound():
    assert layouts.get("orihon8-landscape").binding == "top"
    assert layouts.get("orihon8-landscape").turn == 90


def test_siblings_point_at_each_other():
    assert layouts.get("orihon8").sibling == "orihon8-landscape"
    assert layouts.get("orihon8-landscape").sibling == "orihon8"


def test_rotate90_twice_returns_to_the_original_shape():
    base = layouts.get("orihon8")
    once = layouts.rotate90(base, "tmp1", "tmp1")
    twice = layouts.rotate90(once, "tmp2", "tmp2")
    assert (twice.rows, twice.cols) == (base.rows, base.cols)
    assert twice.turn == base.turn
    # 180 度回した配置になっている
    assert twice.pages == tuple(tuple(reversed(row)) for row in reversed(base.pages))


def test_rotate90_rejects_non_foldbook():
    with pytest.raises(LayoutError, match="折本レイアウトにだけ"):
        layouts.rotate90(layouts.get("nup8"), "x", "x")


def test_turned_layout_rotation_rule_is_enforced():
    """turn=90 では縦の折り線が 180 度ちがいでなければ弾かれること。"""
    bad = layouts.Layout(
        name="bad", title="bad", turn=90,
        pages=((4, 3), (1, 2)),
        rotations=((0, 0), (0, 0)),  # 左右で 180 度ちがっていない
    )
    with pytest.raises(LayoutError, match="turn=90"):
        bad.validate()


# ----------------------------------------------------------------------
# 実際に面付けしたときの無駄
# ----------------------------------------------------------------------
def test_slides_fill_the_landscape_layout_without_rotating(slides, tmp_path):
    result = impose.impose_pdf(
        slides, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8-landscape")
    )
    assert result.rotated_pages == 0        # 回さずにそのまま入る
    assert result.coverage > 0.78
    assert result.landscape is False        # A4 縦の用紙を選ぶ
    assert result.warnings == []


def test_portrait_layout_wastes_space_without_auto_rotate(slides, tmp_path):
    result = impose.impose_pdf(
        slides, tmp_path / "o.pdf",
        impose.ImposeOptions(layout="orihon8", auto_rotate=False),
    )
    assert result.coverage < 0.45
    assert any("orihon8-landscape" in w for w in result.warnings)


def test_auto_rotate_recovers_the_wasted_space(slides, tmp_path):
    plain = impose.impose_pdf(
        slides, tmp_path / "a.pdf",
        impose.ImposeOptions(layout="orihon8", auto_rotate=False),
    )
    rotated = impose.impose_pdf(
        slides, tmp_path / "b.pdf",
        impose.ImposeOptions(layout="orihon8", auto_rotate=True),
    )
    assert rotated.rotated_pages == 8
    assert rotated.coverage > plain.coverage * 1.9
    assert any("90 度回して" in w for w in rotated.warnings)
    assert any("orihon8-landscape" in w for w in rotated.warnings)


def test_auto_rotate_leaves_matching_pages_alone(tmp_path):
    """縦長原稿を縦長パネルに入れるときは回さないこと。"""
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    result = impose.impose_pdf(src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8"))
    assert result.rotated_pages == 0
    assert result.coverage > 0.95


def test_nearly_square_pages_are_not_rotated(tmp_path):
    """ほぼ正方形の原稿が、ページごとにバラバラの向きにならないこと。"""
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="100x101")
    result = impose.impose_pdf(src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8"))
    assert result.rotated_pages == 0


def test_four_three_slides_fit_even_better(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size=SLIDE_4_3)
    result = impose.impose_pdf(
        src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8-landscape")
    )
    assert result.coverage > 0.9
    assert result.rotated_pages == 0


def test_a4_landscape_source_works(tmp_path):
    """A4 横のページ（Word の横向き文書など）も無駄なく入ること。"""
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="297x210")
    result = impose.impose_pdf(
        src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8-landscape")
    )
    assert result.rotated_pages == 0
    assert result.coverage > 0.95      # A4横 と A7横 は相似なのでほぼ隙間なし


def test_landscape_layout_places_pages_where_the_table_says(slides, tmp_path):
    layout = layouts.get("orihon8-landscape")
    out = tmp_path / "o.pdf"
    impose.impose_pdf(
        slides, out,
        impose.ImposeOptions(layout="orihon8-landscape", guides="none"),
    )
    with pymupdf.open(out) as doc:
        page = doc.load_page(0)
        cw = page.rect.width / layout.cols
        ch = page.rect.height / layout.rows
        found = {}
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text.isdigit():
                        continue
                    x = (span["bbox"][0] + span["bbox"][2]) / 2
                    y = (span["bbox"][1] + span["bbox"][3]) / 2
                    found[int(text)] = (
                        (int(y // ch), int(x // cw)),
                        tuple(round(v) for v in line["dir"]),
                    )

    assert set(found) == set(range(1, 9))
    for row, col, page_no, rotation in layout.cells():
        cell, direction = found[page_no]
        assert cell == (row, col), f"ページ {page_no} が {cell}（期待 {(row, col)}）"
        assert direction == ((1, 0) if rotation % 360 == 0 else (-1, 0))


def test_coverage_is_reported(slides, tmp_path):
    result = impose.impose_pdf(
        slides, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8-landscape")
    )
    assert "用紙の使用率" in result.describe()


# ----------------------------------------------------------------------
# 「用紙に合わせて印刷」でできた余白（レターボックス）
# ----------------------------------------------------------------------
@pytest.fixture()
def letterboxed(tmp_path):
    """A7 縦の用紙に 16:9 スライドを合わせて刷った PDF を作る。

    PowerPoint から仮想プリンタへ印刷すると、この形で届くことがある。
    """
    from orihon.paper import get, mm

    w, h = get("A7").size_pt()
    doc = pymupdf.open()
    for i in range(1, 9):
        page = doc.new_page(width=w, height=h)
        sw = w - mm(6)
        sh = sw * 9 / 16
        y0 = (h - sh) / 2
        page.draw_rect(pymupdf.Rect(mm(3), y0, mm(3) + sw, y0 + sh),
                       fill=(1, 1, 1), color=(0.6, 0.6, 0.6), width=0.8)
        page.draw_rect(pymupdf.Rect(mm(3), y0, mm(3) + sw, y0 + mm(5)), fill=(0.15, 0.35, 0.75))
        page.insert_text((mm(6), y0 + mm(12)), f"Slide {i}", fontname="helv", fontsize=9)
    path = tmp_path / "letterboxed.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_uniform_bands_are_detected(letterboxed):
    with pymupdf.open(letterboxed) as doc:
        bands = impose.detect_uniform_bands(doc.load_page(0))
    assert bands.top > 0.25 and bands.bottom > 0.25
    assert bands.remaining < 0.45
    assert bands.significant


def test_a_normal_page_has_no_significant_bands(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=1, size="A7")
    with pymupdf.open(src) as doc:
        assert not impose.detect_uniform_bands(doc.load_page(0)).significant


def test_band_detection_never_eats_a_blank_page(tmp_path):
    """真っ白なページでも、削りすぎて何も残らないことがないこと。"""
    doc = pymupdf.open()
    doc.new_page(width=300, height=400)
    path = tmp_path / "blank.pdf"
    doc.save(str(path))
    doc.close()
    with pymupdf.open(path) as d:
        bands = impose.detect_uniform_bands(d.load_page(0))
    assert bands.top <= 0.45 and bands.bottom <= 0.45
    clip = bands.clip(pymupdf.Rect(0, 0, 300, 400))
    assert clip.width > 0 and clip.height > 0


def test_letterbox_is_warned_about(letterboxed, tmp_path):
    result = impose.impose_pdf(
        letterboxed, tmp_path / "o.pdf",
        impose.ImposeOptions(layout="orihon8-landscape"),
    )
    assert result.trimmed_pages == 0
    assert any("--trim" in w for w in result.warnings)


def test_trim_removes_the_letterbox(letterboxed, tmp_path):
    result = impose.impose_pdf(
        letterboxed, tmp_path / "o.pdf",
        impose.ImposeOptions(layout="orihon8-landscape", trim=True),
    )
    assert result.trimmed_pages == 8
    assert result.rotated_pages == 0   # 切ったあとは横長なので回さずに済む
    assert result.coverage > 0.8
    assert any("切り落とし" in w for w in result.warnings)


def test_trim_leaves_normal_documents_alone(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    result = impose.impose_pdf(
        src, tmp_path / "o.pdf", impose.ImposeOptions(layout="orihon8", trim=True)
    )
    assert result.trimmed_pages == 0
    assert result.coverage > 0.95
