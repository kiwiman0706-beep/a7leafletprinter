#!/usr/bin/env python3
"""レイアウト定義から面付け図（SVG）を書き出す。

    python tools/make_diagrams.py

図はレイアウトのデータそのものから描いているので、``layouts.py`` を直せば
ドキュメントの図も自動的に追随する。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from orihon import configure_stdio, layouts  # noqa: E402
from orihon.layouts import Layout  # noqa: E402

# パネルの縦横は、仕上がりの向き（turn）に合わせて入れ替える
CELL_PORTRAIT = (96, 136)
CELL_LANDSCAPE = (136, 96)
PAD = 28
_ROT_JA = {0: "そのまま", 90: "反時計90度", 180: "天地逆", 270: "時計90度"}
FONT = "'Hiragino Sans','Yu Gothic', 'Noto Sans JP', sans-serif"


def _cell_size(layout: Layout) -> tuple[int, int]:
    return CELL_LANDSCAPE if layout.turn == 90 else CELL_PORTRAIT


def _edge_line(layout: Layout, edge, style: str) -> str:
    CELL_W, CELL_H = _cell_size(layout)
    if edge.orientation == "v":
        x = PAD + (edge.col + 1) * CELL_W
        y1 = PAD + edge.row * CELL_H
        y2 = PAD + (edge.row + 1) * CELL_H
    else:
        y = PAD + (edge.row + 1) * CELL_H
        x1 = PAD + edge.col * CELL_W
        x2 = PAD + (edge.col + 1) * CELL_W
        return f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" {style}/>'
    return f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" {style}/>'


def render(layout: Layout) -> str:
    CELL_W, CELL_H = _cell_size(layout)
    width = PAD * 2 + layout.cols * CELL_W
    height = PAD * 2 + layout.rows * CELL_H + 46

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{layout.title}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<rect x="{PAD}" y="{PAD}" width="{layout.cols * CELL_W}" '
        f'height="{layout.rows * CELL_H}" fill="#fbfbfd" stroke="#222" stroke-width="2"/>',
    ]

    # 折り線（破線）
    for edge in layout.fold_edges():
        parts.append(_edge_line(layout, edge, 'stroke="#9aa0aa" stroke-width="1.5" stroke-dasharray="7 5"'))
    # 切り込み（太い実線 + ハサミ）
    for edge in layout.cut_edges():
        parts.append(_edge_line(layout, edge, 'stroke="#d1495b" stroke-width="3.5"'))

    # ページ番号
    for row, col, page_no, rotation in layout.cells():
        cx = PAD + col * CELL_W + CELL_W / 2
        cy = PAD + row * CELL_H + CELL_H / 2
        transform = f' transform="rotate({-rotation % 360} {cx} {cy})"' if rotation % 360 else ""
        parts.append(
            f'<g{transform}>'
            f'<circle cx="{cx}" cy="{cy}" r="21" fill="none" stroke="#222" stroke-width="1.5"/>'
            f'<text x="{cx}" y="{cy + 8}" text-anchor="middle" font-size="24" '
            f'font-family="{FONT}" fill="#222">{page_no}</text>'
            f'<text x="{cx}" y="{cy + 40}" text-anchor="middle" font-size="11" '
            f'font-family="{FONT}" fill="#98a">{_ROT_JA[rotation % 360]}</text>'
            f"</g>"
        )

    legend_y = PAD + layout.rows * CELL_H + 26
    parts.append(
        f'<line x1="{PAD}" y1="{legend_y - 4}" x2="{PAD + 26}" y2="{legend_y - 4}" '
        f'stroke="#9aa0aa" stroke-width="1.5" stroke-dasharray="7 5"/>'
        f'<text x="{PAD + 32}" y="{legend_y}" font-size="12" font-family="{FONT}" fill="#555">折り線</text>'
        f'<line x1="{PAD + 96}" y1="{legend_y - 4}" x2="{PAD + 122}" y2="{legend_y - 4}" '
        f'stroke="#d1495b" stroke-width="3.5"/>'
        f'<text x="{PAD + 128}" y="{legend_y}" font-size="12" font-family="{FONT}" fill="#555">'
        f'切り込み（ハサミ）</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    # 出力をファイルやパイプに向けても日本語で落ちないようにする
    configure_stdio()
    out_dir = ROOT / "docs" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in ("orihon8", "orihon8-right", "orihon8-landscape", "orihon4", "nup8"):
        layout = layouts.get(name)
        path = out_dir / f"layout-{name}.svg"
        path.write_text(render(layout) + "\n", encoding="utf-8")
        written.append(path)
    for path in written:
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
