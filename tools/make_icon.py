#!/usr/bin/env python3
"""アプリのアイコン（.ico）を生成する。

    python tools/make_icon.py

折本を上から見た形（中央で折られた 2 面と、中央の切り込み）を描いている。
図と同じくコードから起こしているので、あとから色や形を変えるのも容易。
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pymupdf  # noqa: E402

#: ICO に入れる大きさ（Windows がこの中から適したものを選ぶ）
SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND = (0.16, 0.27, 0.53)   # 濃紺
PAPER = (1.0, 1.0, 1.0)
SHADE = (0.82, 0.86, 0.94)        # 折り返しの陰
CUT = (0.85, 0.24, 0.30)          # 切り込みの赤


def draw(size: int) -> bytes:
    """1 枚分の PNG を返す。"""
    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)

    # 角丸の下地
    page.draw_rect(pymupdf.Rect(0, 0, 100, 100), fill=BACKGROUND, color=None,
                   radius=0.22)

    # 開いた折本（左右のページが中央の谷で合わさっている）
    left = [(18, 28), (50, 36), (50, 76), (18, 68)]
    right = [(82, 28), (50, 36), (50, 76), (82, 68)]
    for points, fill in ((left, PAPER), (right, SHADE)):
        shape = page.new_shape()
        shape.draw_polyline([pymupdf.Point(*p) for p in points] + [pymupdf.Point(*points[0])])
        shape.finish(fill=fill, color=None, closePath=True)
        shape.commit()

    # 背（中央の折り目）
    page.draw_line(pymupdf.Point(50, 36), pymupdf.Point(50, 76),
                   color=BACKGROUND, width=1.6)

    # 中央の切り込み（このプロジェクトらしさ）
    page.draw_line(pymupdf.Point(38, 52), pymupdf.Point(62, 52),
                   color=CUT, width=3.2)

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(size / 100, size / 100), alpha=True)
    data = pixmap.tobytes("png")
    doc.close()
    return data


def build_ico(path: Path) -> Path:
    """PNG を並べて ICO に詰める（Vista 以降は PNG を直接扱える）。"""
    images = [(size, draw(size)) for size in SIZES]

    header = struct.pack("<HHH", 0, 1, len(images))
    directory = b""
    payload = b""
    offset = len(header) + 16 * len(images)
    for size, data in images:
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # 256 は 0 で表す決まり
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset,
        )
        payload += data
        offset += len(data)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + directory + payload)
    return path


def main() -> int:
    ico = build_ico(ROOT / "installer" / "setup" / "orihon.ico")
    print(f"{ico.relative_to(ROOT)}  ({ico.stat().st_size:,} bytes, {len(SIZES)} 種類)")
    # 見た目確認用に大きい PNG も出す
    preview = ROOT / "docs" / "images" / "icon.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(draw(256))
    print(f"{preview.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
