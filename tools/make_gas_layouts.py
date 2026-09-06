#!/usr/bin/env python3
"""``layouts.py`` から GAS 版のレイアウト定義（Layouts.gs）を書き出す。

    python tools/make_gas_layouts.py

面付け図やアイコンと同じ考え方で、定義は Python 側の 1 か所だけに置き、
GAS 版はそこから生成する。二重に持つと必ずどちらかが古くなるため。
生成物が最新かどうかは tests/test_gas_layouts.py が確かめている。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from orihon import configure_stdio, layouts, paper  # noqa: E402

OUTPUT = ROOT / "gas" / "Layouts.gs"

HEADER = """/**
 * 折本のレイアウト定義。
 *
 * このファイルは自動生成です。直接編集しないでください。
 * 元は src/orihon/layouts.py で、次のコマンドで作り直せます:
 *
 *     python tools/make_gas_layouts.py
 *
 * pages    … 行優先（先頭が用紙の上段）で並べたページ番号
 * rotations… 同じ形の配列。そのマスの中身が何度回して刷られているか
 * turn     … 仕上がりを立てて読む(0) か、横に倒して上にめくる(90) か
 */
"""

PAPER_HEADER = """
/** 用紙サイズ（ミリ、縦置きのときの寸法）。 */
"""


def main() -> int:
    # 出力をファイルやパイプに向けても日本語で落ちないようにする
    configure_stdio()
    entries = []
    for layout in layouts.PRESETS.values():
        entries.append({
            "name": layout.name,
            "title": layout.title,
            "kind": layout.kind,
            "binding": layout.binding,
            "turn": layout.turn,
            "cols": layout.cols,
            "rows": layout.rows,
            "pages": [list(row) for row in layout.pages],
            "rotations": [list(row) for row in layout.rotations],
            "aliases": list(layout.aliases),
        })

    papers = {p.name: [p.width_mm, p.height_mm] for p in paper.PAPERS.values()}

    def js(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    body = [HEADER]
    body.append(f"const ORIHON_DEFAULT_LAYOUT = {js(layouts.DEFAULT_LAYOUT)};\n\n")
    body.append("const ORIHON_LAYOUTS = [\n")
    for entry in entries:
        body.append("  {\n")
        for key in ("name", "title", "kind", "binding", "turn", "cols", "rows"):
            body.append(f"    {key}: {js(entry[key])},\n")
        # 表は 1 行 1 段にすると、紙の上での並びがそのまま読める
        for key in ("pages", "rotations"):
            rows = ",\n".join(f"      {js(row)}" for row in entry[key])
            body.append(f"    {key}: [\n{rows}\n    ],\n")
        body.append(f"    aliases: {js(entry['aliases'])},\n")
        body.append("  },\n")
    body.append("];\n")
    body.append(PAPER_HEADER)
    body.append("const ORIHON_PAPERS = {\n")
    for name, size in papers.items():
        body.append(f"  {js(name)}: {js(size)},\n")
    body.append("};\n")
    body.append('''
/** 名前か別名からレイアウトを引く。 */
function orihonLayout(name) {
  const key = String(name || ORIHON_DEFAULT_LAYOUT).trim().toLowerCase();
  for (const layout of ORIHON_LAYOUTS) {
    if (layout.name === key || layout.aliases.indexOf(key) >= 0) {
      return layout;
    }
  }
  throw new Error(
    '未知のレイアウト "' + name + '" です。使えるのは: ' +
    ORIHON_LAYOUTS.map(function (l) { return l.name; }).join(', ')
  );
}

/** 用紙名から [幅mm, 高さmm]（縦置き）を引く。 */
function orihonPaper(name) {
  const key = String(name || 'A4').trim();
  for (const paperName of Object.keys(ORIHON_PAPERS)) {
    if (paperName.toLowerCase() === key.toLowerCase()) {
      return ORIHON_PAPERS[paperName];
    }
  }
  const match = key.match(/^(\\d+(?:\\.\\d+)?)\\s*[x×*]\\s*(\\d+(?:\\.\\d+)?)$/);
  if (match) {
    return [parseFloat(match[1]), parseFloat(match[2])];
  }
  throw new Error('未知の用紙 "' + name + '" です。');
}
''')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(body), encoding="utf-8")
    print(f"{OUTPUT.relative_to(ROOT)}  "
          f"（レイアウト {len(entries)} 種類 / 用紙 {len(papers)} 種類）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
