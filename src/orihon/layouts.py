"""折本（おりほん）の面付けレイアウト定義と検証。

1 枚の紙の「片面だけ」に印刷して、折って（必要なら切り込みを入れて）
小冊子にするタイプの折本を扱う。

用語
----
panel  : 用紙を格子状に分割した 1 マス。折本の 1 ページになる。
layout : 各 panel に入るページ番号と、その回転角の表。
fold   : 折り線（隣り合う panel の境界のうち、ページ順が連続しているもの）
cut    : 切り込み（隣り合う panel の境界のうち、折り線にならないもの）

物理的な整合性
--------------
片面刷りの折本は、全 panel が「ページ番号の環（1→2→…→N→1）」に沿って
一筆書きに並んでいる必要がある（ハミルトン閉路）。さらに

* 左右に隣接する panel 同士は回転角が同じ（縦の折り線でそのまま折れる）
* 上下に隣接する panel 同士は回転角が 180 度ちがう（横の折り線で裏返る）

という制約を満たす。``validate()`` はこれを機械的に検査し、
``fold_edges()`` / ``cut_edges()`` はレイアウトから折り線・切り込み位置を
自動的に導出する。図6 の中央のひし形（切り込み）も、この導出結果と一致する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Literal, Sequence

Kind = Literal["foldbook", "accordion", "grid"]

# (row, col) の辺の向き
Orientation = Literal["v", "h"]


class LayoutError(ValueError):
    """レイアウト定義が物理的に成立しないときに送出される。"""


@dataclass(frozen=True)
class Edge:
    """隣り合う 2 つの panel の境界線。

    ``orientation`` が ``"v"`` なら縦線（左右の panel を分ける）、
    ``"h"`` なら横線（上下の panel を分ける）。
    ``(row, col)`` は境界の「左上側」の panel の位置。
    """

    row: int
    col: int
    orientation: Orientation

    @property
    def cells(self) -> tuple[tuple[int, int], tuple[int, int]]:
        if self.orientation == "v":
            return (self.row, self.col), (self.row, self.col + 1)
        return (self.row, self.col), (self.row + 1, self.col)


@dataclass(frozen=True)
class Layout:
    """折本 1 枚分の面付け定義。

    ``pages`` は行優先（先頭が用紙の上段）の 2 次元配列で、1 始まりの
    ページ番号を並べる。``rotations`` は同じ形の配列で 0 / 90 / 180 / 270。
    省略した場合は「上下に隣接する panel は 180 度ちがう」という制約から
    行ごとに自動生成する（最下段が 0 度）。
    """

    name: str
    title: str
    pages: tuple[tuple[int, ...], ...]
    rotations: tuple[tuple[int, ...], ...]
    kind: Kind = "foldbook"
    binding: Literal["left", "right", "none"] = "left"
    description: str = ""
    source: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    # ------------------------------------------------------------------
    # 基本情報
    # ------------------------------------------------------------------
    @property
    def rows(self) -> int:
        return len(self.pages)

    @property
    def cols(self) -> int:
        return len(self.pages[0])

    @property
    def page_count(self) -> int:
        """1 枚の用紙に載るページ数。"""
        return self.rows * self.cols

    def cells(self) -> Iterator[tuple[int, int, int, int]]:
        """``(row, col, page_number, rotation)`` を順に返す。"""
        for r in range(self.rows):
            for c in range(self.cols):
                yield r, c, self.pages[r][c], self.rotations[r][c]

    def position_of(self, page: int) -> tuple[int, int]:
        for r, c, p, _ in self.cells():
            if p == page:
                return r, c
        raise KeyError(f"page {page} is not in layout {self.name!r}")

    # ------------------------------------------------------------------
    # 折り線 / 切り込みの導出
    # ------------------------------------------------------------------
    def internal_edges(self) -> list[Edge]:
        """格子の内部にある境界線をすべて返す。"""
        edges = [
            Edge(r, c, "v") for r in range(self.rows) for c in range(self.cols - 1)
        ]
        edges += [
            Edge(r, c, "h") for r in range(self.rows - 1) for c in range(self.cols)
        ]
        return edges

    def _consecutive_pairs(self) -> set[frozenset[int]]:
        """折り線でつながっていなければならないページの組。

        折本（foldbook）は 1→2→…→N→1 が一筆書きの閉路になる。
        蛇腹（accordion）は行ごとに切り離した帯を貼り合わせるので、
        行をまたぐつながりは折り線ではなく「貼り合わせ」になる。
        グリッド（grid）は折らずに切り離すだけなので折り線はない。
        """
        n = self.page_count
        if self.kind == "grid":
            # 面付けではなく単純な N-up。すべての境界を切り離す。
            return set()
        if self.kind == "accordion":
            pairs = set()
            for row in self.pages:
                for a, b in zip(row, row[1:]):
                    pairs.add(frozenset((a, b)))
            return pairs
        pairs = {frozenset((p, p + 1)) for p in range(1, n)}
        # 表紙(1)と裏表紙(N)は背でつながる＝これも折り線
        pairs.add(frozenset((n, 1)))
        return pairs

    def fold_edges(self) -> list[Edge]:
        """折り線になる境界線。"""
        consecutive = self._consecutive_pairs()
        out = []
        for edge in self.internal_edges():
            (r1, c1), (r2, c2) = edge.cells
            pair = frozenset((self.pages[r1][c1], self.pages[r2][c2]))
            if pair in consecutive:
                out.append(edge)
        return out

    def cut_edges(self) -> list[Edge]:
        """切り込み（ハサミを入れる線）になる境界線。"""
        folds = set(self.fold_edges())
        return [e for e in self.internal_edges() if e not in folds]

    # ------------------------------------------------------------------
    # 検証
    # ------------------------------------------------------------------
    def validate(self) -> None:
        if not self.pages or not self.pages[0]:
            raise LayoutError(f"{self.name}: レイアウトが空です")
        if any(len(row) != self.cols for row in self.pages):
            raise LayoutError(f"{self.name}: 各行の列数が揃っていません")
        if len(self.rotations) != self.rows or any(
            len(row) != self.cols for row in self.rotations
        ):
            raise LayoutError(f"{self.name}: rotations の形が pages と一致しません")

        n = self.page_count
        flat = [p for row in self.pages for p in row]
        if sorted(flat) != list(range(1, n + 1)):
            raise LayoutError(
                f"{self.name}: ページ番号は 1..{n} を 1 回ずつ使ってください (実際: {sorted(flat)})"
            )
        for row in self.rotations:
            for rot in row:
                if rot not in (0, 90, 180, 270):
                    raise LayoutError(f"{self.name}: 回転角は 0/90/180/270 のみ (実際: {rot})")

        if self.kind == "accordion":
            expected = 1
            for r, row in enumerate(self.pages):
                if list(row) != list(range(expected, expected + self.cols)):
                    raise LayoutError(
                        f"{self.name}: 蛇腹折りでは各行が左から連番である必要があります"
                        f"（{r} 行目: {list(row)}）"
                    )
                expected += self.cols
                if len(set(self.rotations[r])) != 1:
                    raise LayoutError(
                        f"{self.name}: 蛇腹折りでは 1 行内の回転角を揃えてください"
                        f"（{r} 行目: {list(self.rotations[r])}）"
                    )

        # 連続ページが隣接しているか（＝一筆書きになっているか）
        needed = self._consecutive_pairs()
        available = set()
        for edge in self.internal_edges():
            (r1, c1), (r2, c2) = edge.cells
            available.add(frozenset((self.pages[r1][c1], self.pages[r2][c2])))
        missing = needed - available
        if missing:
            pretty = ", ".join(
                "-".join(str(x) for x in sorted(pair)) for pair in sorted(missing, key=sorted)
            )
            raise LayoutError(
                f"{self.name}: 連続するページが隣り合っていません ({pretty})。"
                " 折り線が作れないため、この面付けでは折本になりません。"
            )

        # 回転角の整合性
        for edge in self.fold_edges():
            (r1, c1), (r2, c2) = edge.cells
            diff = (self.rotations[r2][c2] - self.rotations[r1][c1]) % 360
            expected = 0 if edge.orientation == "v" else 180
            if diff != expected:
                raise LayoutError(
                    f"{self.name}: {'縦' if edge.orientation == 'v' else '横'}の折り線 "
                    f"({r1},{c1})-({r2},{c2}) の回転差が {diff} 度です"
                    f"（{expected} 度である必要があります）"
                )

    # ------------------------------------------------------------------
    # 表示
    # ------------------------------------------------------------------
    def ascii_art(self) -> str:
        """図6 のような面付け図をテキストで描く。"""
        cuts = {e for e in self.cut_edges()}
        width = 5
        lines = []
        top = "+" + "+".join("-" * width for _ in range(self.cols)) + "+"
        lines.append(top)
        for r in range(self.rows):
            cell_texts = []
            for c in range(self.cols):
                mark = "^" if self.rotations[r][c] % 360 == 0 else "v"
                cell_texts.append(f"{self.pages[r][c]:>2}{mark} ".center(width))
            row_line = "|" + "|".join(cell_texts) + "|"
            lines.append(row_line)
            if r < self.rows - 1:
                seps = []
                for c in range(self.cols):
                    is_cut = Edge(r, c, "h") in cuts
                    seps.append(("=" if is_cut else "-") * width)
                lines.append("+" + "+".join(seps) + "+")
        lines.append(top)
        legend = "  ^ = そのまま / v = 180度回転 / === = 切り込み(ハサミ) / --- = 折り線"
        return "\n".join(lines) + "\n" + legend


def _auto_rotations(pages: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    """最下段を 0 度として、1 段上がるごとに 180 度ずつ反転させる。"""
    rows = len(pages)
    return tuple(
        tuple(180 if (rows - 1 - r) % 2 else 0 for _ in row) for r, row in enumerate(pages)
    )


def _mirror(pages: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    """列の並びを左右反転する（＝綴じ方向を反転する）。"""
    return tuple(tuple(reversed(row)) for row in pages)


def _make(
    name: str,
    title: str,
    pages: Sequence[Sequence[int]],
    *,
    kind: Kind = "foldbook",
    binding: Literal["left", "right", "none"] = "left",
    description: str = "",
    source: str = "",
    aliases: Sequence[str] = (),
    rotations: Sequence[Sequence[int]] | None = None,
) -> Layout:
    pages_t = tuple(tuple(row) for row in pages)
    rot_t = (
        tuple(tuple(row) for row in rotations)
        if rotations is not None
        else _auto_rotations(pages_t)
    )
    layout = Layout(
        name=name,
        title=title,
        pages=pages_t,
        rotations=rot_t,
        kind=kind,
        binding=binding,
        description=description,
        source=source,
        aliases=tuple(aliases),
    )
    layout.validate()
    return layout


# ----------------------------------------------------------------------
# プリセット
# ----------------------------------------------------------------------
# 図6（キンコーズ「折本の作り方」）の面付け:
#
#     ┌───┬───┬───┬───┐
#     │ 7 │ 6 │ 5 │ 4 │  ← 上段はすべて 180 度回転
#     ├───┼═══┼═══┼───┤  ← 中央 2 マス分が切り込み
#     │ 8 │ 1 │ 2 │ 3 │  ← 下段はそのまま
#     └───┴───┴───┴───┘
#
# 表紙(1)の背は左側（8 との境）にあるので左綴じ（横書き向き）。
_ORIHON8_PAGES = ((7, 6, 5, 4), (8, 1, 2, 3))

ORIHON8 = _make(
    "orihon8",
    "折本 8ページ（A4→A7・左綴じ）",
    _ORIHON8_PAGES,
    binding="left",
    aliases=("a7", "8p", "orihon8-left"),
    source="キンコーズ・ジャパン「手軽に作れる折本の作り方」図6",
    description=(
        "A4 を 8 分割し、中央 2 マス分に切り込みを入れて折る、いちばん一般的な折本。"
        "A4 から A7（74×105mm）8 ページの小冊子ができる。"
    ),
)

ORIHON8_RIGHT = _make(
    "orihon8-right",
    "折本 8ページ（A4→A7・右綴じ）",
    _mirror(_ORIHON8_PAGES),
    binding="right",
    aliases=("8p-right", "a7-right"),
    description="orihon8 を左右反転したもの。縦書き・マンガなど右綴じの本文向け。",
)

# 4ページ（切り込み不要）
#     ┌───┬───┐
#     │ 3 │ 2 │  ← 180 度回転
#     ├───┼───┤
#     │ 4 │ 1 │
#     └───┴───┘
_ORIHON4_PAGES = ((3, 2), (4, 1))

ORIHON4 = _make(
    "orihon4",
    "折本 4ページ（A4→A6・左綴じ）",
    _ORIHON4_PAGES,
    binding="left",
    aliases=("a6", "4p"),
    description="A4 を 4 分割。切り込み不要で、二つ折り→二つ折りだけで作れる。",
)

ORIHON4_RIGHT = _make(
    "orihon4-right",
    "折本 4ページ（A4→A6・右綴じ）",
    _mirror(_ORIHON4_PAGES),
    binding="right",
    aliases=("4p-right", "a6-right"),
    description="orihon4 を左右反転したもの。",
)

# 蛇腹折り（経本折り）。切り込みなし・ページ数自由。
ACCORDION8 = _make(
    "accordion8",
    "蛇腹折り 8ページ（A4横・切り込みなし）",
    ((1, 2, 3, 4), (5, 6, 7, 8)),
    kind="accordion",
    binding="none",
    aliases=("jabara8",),
    rotations=((0, 0, 0, 0), (0, 0, 0, 0)),
    description=(
        "上段・下段をそれぞれ横に切り離してから、山折り谷折りを繰り返す蛇腹（経本）折り。"
        "折本の伝統的な形式で、切り離した 2 本をつなげば 8 コマの帯になる。"
    ),
)

ACCORDION4 = _make(
    "accordion4",
    "蛇腹折り 4ページ（A4横・切り込みなし）",
    ((1, 2, 3, 4),),
    kind="accordion",
    binding="none",
    aliases=("jabara4",),
    rotations=((0, 0, 0, 0),),
    description="A4 を縦に 4 分割した帯を、そのまま蛇腹に折る。",
)

# 折らずに「切り離すだけ」の N-up（A7 チラシを 8 面付けする等）
NUP8 = _make(
    "nup8",
    "8面付け A7（折らずに切り離すだけ）",
    ((1, 2, 3, 4), (5, 6, 7, 8)),
    kind="grid",
    binding="none",
    aliases=("8up", "a7x8"),
    rotations=((0, 0, 0, 0), (0, 0, 0, 0)),
    description=(
        "A4 を 8 分割して A7 のカード／チラシを面付けする。折本ではないので折り線はなく、"
        "すべての境界が切り取り線になる。`--fill repeat` と組み合わせると"
        "「1 ページの原稿を 8 面に複製」ができる。"
    ),
)

NUP4 = _make(
    "nup4",
    "4面付け A6（折らずに切り離すだけ）",
    ((1, 2), (3, 4)),
    kind="grid",
    binding="none",
    aliases=("4up", "a6x4"),
    rotations=((0, 0), (0, 0)),
    description="A4 を 4 分割して A6 を面付けする。",
)

NUP2 = _make(
    "nup2",
    "2面付け A5（折らずに切り離すだけ）",
    ((1, 2),),
    kind="grid",
    binding="none",
    aliases=("2up", "a5x2"),
    rotations=((0, 0),),
    description="A4 横を 2 分割して A5 を面付けする。",
)


PRESETS: dict[str, Layout] = {}
for _layout in (
    ORIHON8,
    ORIHON8_RIGHT,
    ORIHON4,
    ORIHON4_RIGHT,
    ACCORDION8,
    ACCORDION4,
    NUP8,
    NUP4,
    NUP2,
):
    PRESETS[_layout.name] = _layout

_ALIASES: dict[str, str] = {}
for _layout in PRESETS.values():
    for _alias in _layout.aliases:
        _ALIASES[_alias] = _layout.name


DEFAULT_LAYOUT = ORIHON8.name


def get(name: str) -> Layout:
    """プリセット名またはエイリアスからレイアウトを取得する。"""
    key = (name or "").strip().lower()
    if key in PRESETS:
        return PRESETS[key]
    if key in _ALIASES:
        return PRESETS[_ALIASES[key]]
    known = ", ".join(sorted(PRESETS))
    raise KeyError(f"未知のレイアウト {name!r} です。利用できるのは: {known}")


def names() -> list[str]:
    return list(PRESETS)
