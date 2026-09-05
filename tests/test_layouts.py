"""レイアウト定義の検証。"""

import pytest

from orihon import layouts
from orihon.layouts import Edge, LayoutError


def test_all_presets_are_physically_valid():
    for layout in layouts.PRESETS.values():
        layout.validate()


def test_orihon8_matches_kinkos_figure6():
    """キンコーズ「折本の作り方」図6 と同じ面付けになっていること。

        7(逆) 6(逆) 5(逆) 4(逆)
        8     1     2     3
    """
    layout = layouts.get("orihon8")
    assert layout.pages == ((7, 6, 5, 4), (8, 1, 2, 3))
    assert layout.rotations == ((180, 180, 180, 180), (0, 0, 0, 0))
    assert (layout.cols, layout.rows) == (4, 2)


def test_orihon8_cut_is_the_centre_slit():
    """切り込みが「中央 2 マス分の横線」だけであること（図6 のひし形）。"""
    layout = layouts.get("orihon8")
    cuts = set(layout.cut_edges())
    assert cuts == {Edge(0, 1, "h"), Edge(0, 2, "h")}
    # 残りの内部境界はすべて折り線
    assert len(layout.fold_edges()) == len(layout.internal_edges()) - 2


def test_orihon4_needs_no_cut():
    assert layouts.get("orihon4").cut_edges() == []


def test_right_bound_is_mirror_of_left_bound():
    left = layouts.get("orihon8")
    right = layouts.get("orihon8-right")
    assert right.pages == tuple(tuple(reversed(row)) for row in left.pages)
    assert left.binding == "left" and right.binding == "right"


def test_cover_is_next_to_back_cover():
    """表紙(1)と裏表紙(N)が隣り合っている＝そこが背になる。"""
    for name in ("orihon8", "orihon8-right", "orihon4", "orihon4-right"):
        layout = layouts.get(name)
        r1, c1 = layout.position_of(1)
        rn, cn = layout.position_of(layout.page_count)
        assert abs(r1 - rn) + abs(c1 - cn) == 1


def test_aliases_resolve():
    assert layouts.get("a7") is layouts.get("orihon8")
    assert layouts.get("8UP") is layouts.get("nup8")


def test_unknown_layout_raises():
    with pytest.raises(KeyError):
        layouts.get("そんなレイアウトはない")


def test_layout_rejects_non_adjacent_consecutive_pages():
    bad = layouts.Layout(
        name="bad", title="bad",
        pages=((1, 3), (2, 4)),
        rotations=((180, 180), (0, 0)),
    )
    with pytest.raises(LayoutError, match="隣り合っていません"):
        bad.validate()


def test_layout_rejects_wrong_rotation():
    bad = layouts.Layout(
        name="bad", title="bad",
        pages=((3, 2), (4, 1)),
        rotations=((0, 0), (0, 0)),  # 上下で 180 度ちがっていない
    )
    with pytest.raises(LayoutError, match="回転差"):
        bad.validate()


def test_layout_rejects_duplicate_pages():
    bad = layouts.Layout(
        name="bad", title="bad",
        pages=((1, 1), (2, 2)),
        rotations=((180, 180), (0, 0)),
    )
    with pytest.raises(LayoutError, match="1 回ずつ"):
        bad.validate()


def test_accordion_rows_must_be_sequential():
    bad = layouts.Layout(
        name="bad", title="bad", kind="accordion",
        pages=((1, 3, 2, 4),),
        rotations=((0, 0, 0, 0),),
    )
    with pytest.raises(LayoutError, match="連番"):
        bad.validate()


def test_ascii_art_marks_cuts():
    art = layouts.get("orihon8").ascii_art()
    assert "=====" in art  # 切り込み
    assert " 1^" in art and " 7v" in art
