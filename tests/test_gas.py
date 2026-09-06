"""GAS 版が Python 版と食い違っていないことを確かめる。

GAS のコードのうち Google の API を使わない部分（レイアウト表と幾何計算）は
Node でそのまま走らせられる。ここでは実際に走らせて、Python 側と
同じ答えになることを確かめている。定義は Python 側の 1 か所にあり、
GAS 側は生成物なので、ずれたらこのテストが落ちる。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from math import log
from pathlib import Path

import pymupdf
import pytest

from orihon import layouts, paper, unimpose

ROOT = Path(__file__).resolve().parents[1]
GAS = ROOT / "gas"

node = pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")


def _run_gas(script: str) -> object:
    """GAS の純粋関数を読み込んでから、渡した式を評価する。"""
    sources = "\n".join(
        (GAS / name).read_text(encoding="utf-8") for name in ("Layouts.gs", "Unimpose.gs")
    )
    runner = (
        "const sources = " + json.dumps(sources) + ";\n"
        "const check = " + json.dumps(script) + ";\n"
        "console.log(eval(sources + check));\n"
    )
    result = subprocess.run(
        ["node", "-e", runner], capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        # Windows では既定が cp1252 になり、日本語を含む入出力で読み書きが壊れる
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ----------------------------------------------------------------------
# 生成物が最新か
# ----------------------------------------------------------------------
def test_generated_layouts_are_up_to_date():
    """tools/make_gas_layouts.py を流し直しても中身が変わらないこと。"""
    before = (GAS / "Layouts.gs").read_text(encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "tools/make_gas_layouts.py"],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        encoding="utf-8", errors="replace", env=env,
    )
    assert result.returncode == 0, result.stderr
    after = (GAS / "Layouts.gs").read_text(encoding="utf-8")
    assert before == after, (
        "gas/Layouts.gs が古くなっています。"
        "python tools/make_gas_layouts.py を実行して commit してください。"
    )


def test_every_preset_is_exported():
    text = (GAS / "Layouts.gs").read_text(encoding="utf-8")
    for name in layouts.names():
        assert f'name: "{name}"' in text


# ----------------------------------------------------------------------
# 幾何計算が Python と一致するか
# ----------------------------------------------------------------------
@node
def test_gas_matches_python_for_every_layout():
    got = {
        entry["name"]: entry
        for entry in _run_gas(
            """
            const out = [];
            for (const layout of ORIHON_LAYOUTS) {
              const size = panelSizePt(layout, 'A4');
              const cells = [];
              for (let p = 1; p <= layout.cols * layout.rows; p++) {
                const pos = findPage(layout, p);
                cells.push([p, pos.row, pos.col, layout.rotations[pos.row][pos.col]]);
              }
              const turns = {};
              for (const t of [0, 90, 180, 270]) {
                const c = sourceCell(layout, 0, 0, t);
                turns[t] = [c.row, c.col];
              }
              out.push({name: layout.name,
                        panel: [+size.width.toFixed(4), +size.height.toFixed(4)],
                        cells: cells, turns: turns});
            }
            JSON.stringify(out);
            """
        )
    }
    assert set(got) == set(layouts.names())

    a4 = paper.get("A4")
    ideal = abs(log(a4.width_mm / a4.height_mm))
    for name, layout in layouts.PRESETS.items():
        entry = got[name]

        # 復元後 1 ページの大きさ
        best = None
        for landscape in (False, True):
            width, height = a4.size_pt(landscape)
            panel_w, panel_h = width / layout.cols, height / layout.rows
            score = abs(abs(log(panel_w / panel_h)) - ideal)
            if (panel_w > panel_h) == (layout.turn == 90):
                score -= 1e-6
            if best is None or score < best[0]:
                best = (score, panel_w, panel_h)
        assert entry["panel"][0] == pytest.approx(best[1], abs=0.01), name
        assert entry["panel"][1] == pytest.approx(best[2], abs=0.01), name

        # ページ番号 → マスと回転の対応
        expected_cells = []
        for page_no in range(1, layout.page_count + 1):
            row, col = layout.position_of(page_no)
            expected_cells.append([page_no, row, col, layout.rotations[row][col]])
        assert entry["cells"] == expected_cells, name

        # シートを回して読むときのマスの読み替え
        content = pymupdf.Rect(0, 0, layout.cols * 100, layout.rows * 100)
        for turn in (0, 90, 180, 270):
            clip = unimpose._panel_clip(content, layout, 0, 0, turn)
            cols = layout.cols if turn % 180 == 0 else layout.rows
            rows = layout.rows if turn % 180 == 0 else layout.cols
            expected = [round(clip.y0 / (content.height / rows)),
                        round(clip.x0 / (content.width / cols))]
            assert entry["turns"][str(turn)] == expected, f"{name} turn={turn}"


@node
def test_gas_resolves_layout_aliases():
    got = _run_gas(
        "JSON.stringify([orihonLayout('a7').name, orihonLayout('SLIDE').name,"
        " orihonLayout('8up').name]);"
    )
    assert got == ["orihon8", "orihon8-landscape", "nup8"]


@node
def test_gas_rejects_an_unknown_layout():
    got = _run_gas(
        "let m = ''; try { orihonLayout('でたらめ'); } catch (e) { m = e.message; }"
        " JSON.stringify(m);"
    )
    assert "未知のレイアウト" in got


@node
def test_gas_paper_lookup_matches_python():
    got = _run_gas(
        "JSON.stringify([orihonPaper('A4'), orihonPaper('a7'), orihonPaper('210x297')]);"
    )
    assert got[0] == [paper.get("A4").width_mm, paper.get("A4").height_mm]
    assert got[1] == [paper.get("A7").width_mm, paper.get("A7").height_mm]
    assert got[2] == [210.0, 297.0]


@node
def test_gas_millimetre_conversion_matches_python():
    from orihon.paper import mm

    got = _run_gas("JSON.stringify([mmToPt(210), mmToPt(1), mmToPt(0)]);")
    assert got[0] == pytest.approx(mm(210))
    assert got[1] == pytest.approx(mm(1))
    assert got[2] == 0


# ----------------------------------------------------------------------
# 体裁
# ----------------------------------------------------------------------
def test_manifest_declares_what_the_script_needs():
    manifest = json.loads((GAS / "appsscript.json").read_text(encoding="utf-8"))
    services = [s["serviceId"] for s in manifest["dependencies"]["enabledAdvancedServices"]]
    assert "slides" in services          # 切り抜きとページの大きさに必要
    scopes = manifest["oauthScopes"]
    assert any("drive" in s for s in scopes)
    assert any("presentations" in s for s in scopes)
    assert any("script.scriptapp" in s for s in scopes)   # トリガーの登録


@node
def test_all_gas_files_are_syntactically_valid():
    """GAS のファイルが JavaScript として構文エラーを起こさないこと。"""
    for name in sorted(p.name for p in GAS.glob("*.gs")):
        source = (GAS / name).read_text(encoding="utf-8")
        result = subprocess.run(
            ["node", "--check", "-"], input=source,
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"
