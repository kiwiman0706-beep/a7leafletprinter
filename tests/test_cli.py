"""コマンドラインの検証。"""

import pytest

from orihon import cli, config, impose


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_layouts_lists_every_preset(home, capsys):
    assert cli.main(["layouts", "-v"]) == 0
    out = capsys.readouterr().out
    assert "[orihon8]" in out and "[nup8]" in out
    assert "=====" in out  # 面付け図の切り込み


def test_doctor_runs(home, capsys):
    cli.main(["doctor"])
    assert "PyMuPDF" in capsys.readouterr().out


def test_printers_runs(home, capsys):
    assert cli.main(["printers"]) == 0
    assert "バックエンド" in capsys.readouterr().out


def test_impose_writes_a_sheet(home, tmp_path, capsys):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    out = tmp_path / "o.pdf"
    assert cli.main(["impose", str(src), "-o", str(out)]) == 0
    assert out.exists()
    assert "出力枚数   : 1" in capsys.readouterr().out


def test_impose_default_output_name(home, tmp_path):
    src = impose.write_test_pdf(tmp_path / "原稿.pdf", pages=8, size="A7")
    assert cli.main(["impose", str(src)]) == 0
    assert (tmp_path / "原稿_orihon8.pdf").exists()


def test_impose_options_are_honoured(home, tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=4, size="A6")
    out = tmp_path / "o.pdf"
    assert cli.main([
        "impose", str(src), "-o", str(out),
        "--layout", "orihon4", "--paper", "B5", "--orientation", "landscape",
        "--guides", "full", "--margin", "2", "--numbers",
    ]) == 0
    import pymupdf

    with pymupdf.open(out) as doc:
        rect = doc.load_page(0).rect
    assert rect.width > rect.height  # landscape


def test_impose_rejects_missing_input(home, tmp_path, capsys):
    assert cli.main(["impose", str(tmp_path / "ない.pdf")]) == 1


def test_impose_rejects_unknown_layout(home, tmp_path, capsys):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    assert cli.main(["impose", str(src), "--layout", "でたらめ"]) == 1
    assert "未知のレイアウト" in capsys.readouterr().err


def test_config_show_and_set(home, capsys):
    assert cli.main(["config"]) == 0
    assert "layout = 'orihon8'" in capsys.readouterr().out

    assert cli.main(["config", "--set", "layout=orihon4",
                     "--set", "safe_margin_mm=1.5",
                     "--set", "keep_source=true"]) == 0
    cfg = config.load()
    assert (cfg.layout, cfg.safe_margin_mm, cfg.keep_source) == ("orihon4", 1.5, True)


def test_config_set_rejects_unknown_key(home, capsys):
    assert cli.main(["config", "--set", "そんなキーはない=1"]) == 1
    assert "未知の設定キー" in capsys.readouterr().err


def test_config_set_rejects_bad_value(home, capsys):
    assert cli.main(["config", "--set", "layout=でたらめ"]) == 1
    assert "設定エラー" in capsys.readouterr().err


def test_config_set_requires_equals(home, capsys):
    assert cli.main(["config", "--set", "layout"]) == 1


def test_selftest_produces_files(home, tmp_path, capsys):
    out_dir = tmp_path / "st"
    assert cli.main(["selftest", "-d", str(out_dir)]) == 0
    assert (out_dir / "テスト原稿.pdf").exists()
    assert (out_dir / "テスト_orihon8.pdf").exists()


def test_watch_once_processes_the_spool(home, tmp_path, capsys):
    cli.main(["config", "--set", "output_mode=save",
              "--set", f"output_dir={tmp_path / 'out'}",
              "--set", "settle_sec=0"])
    spool = config.load().resolved_spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    impose.write_test_pdf(spool / "job.pdf", pages=8, size="A7")

    assert cli.main(["watch", "--once"]) == 0
    assert "1 件処理しました" in capsys.readouterr().out
    assert list((tmp_path / "out").glob("*.pdf"))


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0


def test_doctor_warns_about_a_stale_spool(home, capsys):
    from orihon import config as _config

    spool = _config.load().resolved_spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    impose.write_test_pdf(spool / "job.pdf", pages=1, size="A7")

    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "未処理の PDF が 1 個" in out


def test_doctor_reports_a_running_watcher(home, capsys, monkeypatch):
    from orihon import watcher as _watcher

    monkeypatch.setattr(_watcher, "running_pid", lambda cfg: 4242)
    cli.main(["doctor"])
    assert "PID 4242" in capsys.readouterr().out


def test_impose_print_dialog_flag(home, tmp_path, monkeypatch, capsys):
    from orihon import winprint

    launched = []
    monkeypatch.setattr(winprint, "_launch", lambda cmd, **kw: launched.append(cmd))
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    out = tmp_path / "o.pdf"

    assert cli.main(["impose", str(src), "-o", str(out), "--print-dialog"]) == 0
    assert len(launched) == 1
    assert "出力動作" in capsys.readouterr().out


def test_printdialog_rejects_missing_file(home, tmp_path, capsys):
    assert cli.main(["printdialog", str(tmp_path / "ない.pdf")]) == 1
    assert "見つかりません" in capsys.readouterr().err


def test_printers_lists_dialog_backends(home, capsys):
    assert cli.main(["printers"]) == 0
    out = capsys.readouterr().out
    assert "印刷ダイアログを出せる手段" in out
    assert "無人印刷" in out


def test_output_survives_a_non_utf8_locale(tmp_path):
    """出力をリダイレクトしても、日本語で落ちないこと。

    Windows で出力をファイルやパイプに向けると、その環境のコードページ
    （英語版なら cp1252）でエンコードしようとして UnicodeEncodeError になる。
    コンソールに直接出す分には起きないので気づきにくい。
    ここでは PYTHONIOENCODING で同じ状況を作って確かめている。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    src_dir = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src_dir) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "cp1252"
    env["ORIHON_HOME"] = str(tmp_path / "home")

    proc = subprocess.run(
        [sys.executable, "-m", "orihon", "layouts", "-v"],
        capture_output=True, env=env, cwd=str(src_dir), timeout=60,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "折本".encode() in proc.stdout      # UTF-8 でそのまま出ている
    assert b"charmap" not in proc.stderr
