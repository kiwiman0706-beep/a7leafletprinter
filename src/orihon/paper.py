"""用紙サイズの定義とミリ／ポイント変換。"""

from __future__ import annotations

from dataclasses import dataclass

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


def mm(value: float) -> float:
    """ミリメートルを PDF のポイント（1/72 インチ）に変換する。"""
    return value * PT_PER_INCH / MM_PER_INCH


def pt_to_mm(value: float) -> float:
    return value * MM_PER_INCH / PT_PER_INCH


@dataclass(frozen=True)
class Paper:
    """用紙。``width_mm`` / ``height_mm`` は縦置き（portrait）時の寸法。"""

    name: str
    width_mm: float
    height_mm: float

    def size_pt(self, landscape: bool = False) -> tuple[float, float]:
        w, h = mm(self.width_mm), mm(self.height_mm)
        return (h, w) if landscape else (w, h)


_PAPERS = [
    Paper("A3", 297.0, 420.0),
    Paper("A4", 210.0, 297.0),
    Paper("A5", 148.0, 210.0),
    Paper("A6", 105.0, 148.0),
    Paper("A7", 74.0, 105.0),
    Paper("B4", 257.0, 364.0),   # JIS B
    Paper("B5", 182.0, 257.0),   # JIS B
    Paper("B6", 128.0, 182.0),   # JIS B
    Paper("Letter", 215.9, 279.4),
    Paper("Legal", 215.9, 355.6),
    Paper("Tabloid", 279.4, 431.8),
]

PAPERS: dict[str, Paper] = {p.name.lower(): p for p in _PAPERS}

DEFAULT_PAPER = "A4"


def get(name: str) -> Paper:
    """用紙名から ``Paper`` を得る。``210x297`` のような直接指定も受け付ける。"""
    key = (name or "").strip().lower()
    if key in PAPERS:
        return PAPERS[key]
    for sep in ("x", "×", "*"):
        if sep in key:
            left, _, right = key.partition(sep)
            try:
                w, h = float(left.strip()), float(right.strip())
            except ValueError:
                break
            if w > 0 and h > 0:
                return Paper(f"{w:g}x{h:g}mm", w, h)
    known = ", ".join(p.name for p in _PAPERS)
    raise KeyError(f"未知の用紙 {name!r} です。利用できるのは: {known}（または 210x297 のようなmm指定）")


def names() -> list[str]:
    return [p.name for p in _PAPERS]
