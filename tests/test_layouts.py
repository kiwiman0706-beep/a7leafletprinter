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


# ----------------------------------------------------------------------
# 自分の折り方を直接指定する
# ----------------------------------------------------------------------
def test_spec_matches_the_bundled_preset():
    """図6 の並びを書き下すと、同梱のプリセットと同じものになること。"""
    spec = layouts.get("7,6,5,4/8,1,2,3")
    preset = layouts.get("orihon8")
    assert spec.pages == preset.pages
    assert spec.rotations == preset.rotations
    assert set(spec.cut_edges()) == set(preset.cut_edges())


def test_spec_supports_the_other_common_zine_fold():
    """海外でよくある zine 折り（表紙が右下）も扱えること。

    同じ 8 ページの折本でも、折り方によって表紙の来るマスが変わる。
    プリセットに無い並びでも、書き下せば使える。
    """
    zine = layouts.get("5,4,3,2/6,7,8,1")
    zine.validate()
    assert zine.position_of(1) == (1, 3)          # 表紙は右下
    # 切り込みの位置は図6 と同じ（中央 2 マス分の横線）
    assert set(zine.cut_edges()) == {Edge(0, 1, "h"), Edge(0, 2, "h")}


def test_spec_accepts_spaces_and_extra_separators():
    assert layouts.get(" 7 6 5 4 / 8 1 2 3 ").pages == ((7, 6, 5, 4), (8, 1, 2, 3))


def test_spec_finds_the_turned_variant():
    """横長パネル（天綴じ）の並びも、回転角を自動で決められること。"""
    turned = layouts.get("8,7/1,6/2,5/3,4")
    turned.validate()
    assert turned.turn == 90
    assert turned.rotations == layouts.get("orihon8-landscape").rotations


def test_spec_puts_the_cover_upright():
    for spec in ("7,6,5,4/8,1,2,3", "5,4,3,2/6,7,8,1", "8,7/1,6/2,5/3,4"):
        layout = layouts.get(spec)
        row, col = layout.position_of(1)
        assert layout.rotations[row][col] == 0, spec


def test_spec_rejects_an_impossible_arrangement():
    with pytest.raises(LayoutError, match="折本になりません"):
        layouts.get("1,2,3,4/5,6,7,8")


def test_spec_rejects_nonsense():
    with pytest.raises(LayoutError, match="読めません"):
        layouts.parse_spec("あ,い/う,え")


def test_unknown_name_still_raises_key_error():
    with pytest.raises(KeyError):
        layouts.get("そんな名前はない")
