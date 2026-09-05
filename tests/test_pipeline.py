"""設定・ジョブ処理・スプール監視の検証。"""

import os
import time

import pymupdf
import pytest

from orihon import config, impose, job, watcher


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """ORIHON_HOME を一時フォルダに向ける。"""
    root = tmp_path / "home"
    monkeypatch.setenv("ORIHON_HOME", str(root))
    return root


@pytest.fixture()
def cfg(home, tmp_path):
    c = config.load_or_create()
    c.output_mode = "save"
    c.output_dir = str(tmp_path / "out")
    c.settle_sec = 0.0
    c.poll_interval_sec = 0.05
    return c


# ----------------------------------------------------------------------
# 設定
# ----------------------------------------------------------------------
def test_config_round_trip(home):
    c = config.load_or_create()
    c.layout = "orihon8-right"
    c.safe_margin_mm = 2.5
    c.keep_source = True
    c.save()
    again = config.load()
    assert (again.layout, again.safe_margin_mm, again.keep_source) == (
        "orihon8-right", 2.5, True,
    )


def test_config_defaults_when_missing(home):
    assert not config.config_path().exists()
    c = config.load()
    assert c.layout == "orihon8"
    assert c.validate() == []


def test_config_ignores_unknown_keys(home):
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"layout": "orihon4", "むかしの設定": 1}', encoding="utf-8")
    assert config.load().layout == "orihon4"


def test_config_survives_broken_json(home):
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ こわれている", encoding="utf-8")
    assert config.load().layout == config.Config().layout


def test_config_validate_reports_problems(home):
    c = config.Config(layout="ない", guides="へんな値", safe_margin_mm=-1)
    problems = c.validate()
    assert len(problems) == 3


def test_impose_options_follow_config(home):
    c = config.Config(layout="orihon4", paper="B5", guides="full", safe_margin_mm=1.0)
    opts = c.impose_options()
    assert (opts.layout, opts.paper, opts.guides, opts.safe_margin_mm) == (
        "orihon4", "B5", "full", 1.0,
    )


# ----------------------------------------------------------------------
# ジョブ処理
# ----------------------------------------------------------------------
def test_process_pdf_saves_imposed_output(cfg, tmp_path):
    src = impose.write_test_pdf(tmp_path / "src.pdf", pages=8, size="A7")
    result = job.process_pdf(src, cfg)
    assert result.output.exists()
    with pymupdf.open(result.output) as doc:
        assert doc.page_count == 1
    assert result.outcome is not None and "保存" in result.outcome.method


def test_output_name_uses_pdf_title(cfg, tmp_path):
    src = tmp_path / "job.pdf"
    doc = impose.make_test_document(pages=8)
    doc.set_metadata({"title": "打ち合わせメモ"})
    doc.save(str(src))
    doc.close()
    result = job.process_pdf(src, cfg, display_name="job.pdf")
    assert result.output.name.startswith("打ち合わせメモ_orihon8_")


def test_output_name_falls_back_to_file_stem(cfg, tmp_path):
    src = impose.write_test_pdf(tmp_path / "原稿.pdf", pages=8, size="A7")
    result = job.process_pdf(src, cfg, display_name="原稿.pdf")
    assert result.output.name.startswith("原稿_orihon8_")


def test_temp_suffixes_are_stripped_from_name(cfg, tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    result = job.process_pdf(src, cfg, display_name="job.pdf.1234.orihon-processing")
    assert result.output.name.startswith("job_orihon8_")


def test_illegal_filename_characters_are_replaced(cfg, tmp_path):
    src = tmp_path / "s.pdf"
    doc = impose.make_test_document(pages=8)
    doc.set_metadata({"title": 'a/b\\c:d*e?f"g<h>i|j'})
    doc.save(str(src))
    doc.close()
    result = job.process_pdf(src, cfg)
    assert not set(result.output.stem) & set('/\\:*?"<>|')


def test_keep_source_copies_the_original(cfg, tmp_path):
    cfg.keep_source = True
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    result = job.process_pdf(src, cfg)
    assert result.kept_source is not None and result.kept_source.exists()


def test_existing_output_gets_a_suffix(cfg, tmp_path):
    cfg.filename_template = "同じ名前.pdf"
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    first = job.process_pdf(src, cfg).output
    second = job.process_pdf(src, cfg).output
    assert first != second
    assert second.name == "同じ名前(2).pdf"


def test_bad_filename_template_falls_back(cfg, tmp_path):
    cfg.filename_template = "{存在しない項目}.pdf"
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    assert job.process_pdf(src, cfg).output.exists()


# ----------------------------------------------------------------------
# 監視
# ----------------------------------------------------------------------
def test_watcher_picks_up_a_spooled_pdf(cfg):
    spool = cfg.resolved_spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    impose.write_test_pdf(spool / "job.pdf", pages=8, size="A7")

    w = watcher.Watcher(cfg)
    results = w.process_once()

    assert len(results) == 1
    assert results[0].output.exists()
    # スプールは空になっている（次のジョブを受けられる）
    assert list(spool.iterdir()) == []


def test_watcher_ignores_files_still_being_written(cfg):
    spool = cfg.resolved_spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    cfg.settle_sec = 30.0
    target = spool / "job.pdf"
    target.write_bytes("%PDF-1.4 まだ書き込み中".encode("utf-8"))

    assert watcher.Watcher(cfg).process_once() == []
    assert target.exists()


def test_watcher_ignores_empty_files(cfg):
    spool = cfg.resolved_spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    (spool / "job.pdf").write_bytes(b"")
    assert watcher.Watcher(cfg).process_once() == []


def test_watcher_quarantines_broken_pdfs(cfg):
    spool = cfg.resolved_spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    (spool / "job.pdf").write_bytes(b"this is not a pdf at all, sorry")
    time.sleep(0.01)

    errors = []
    w = watcher.Watcher(cfg, on_error=lambda p, e: errors.append(p))
    assert w.process_once() == []
    assert len(errors) == 1
    assert list(spool.iterdir()) == []
    failed = list((cfg.processed_dir() / "failed").glob("*.pdf"))
    assert len(failed) == 1


def test_watcher_handles_several_jobs(cfg):
    spool = cfg.resolved_spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        impose.write_test_pdf(spool / f"job{i}.pdf", pages=8, size="A7")
    results = watcher.Watcher(cfg).process_once()
    assert len(results) == 3
    assert len({r.output for r in results}) == 3


def test_watcher_callback_fires(cfg):
    spool = cfg.resolved_spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    impose.write_test_pdf(spool / "job.pdf", pages=8, size="A7")
    seen = []
    watcher.Watcher(cfg, on_job=seen.append).process_once()
    assert len(seen) == 1


def test_watcher_cleanup_removes_old_files(cfg):
    processed = cfg.processed_dir()
    processed.mkdir(parents=True, exist_ok=True)
    old = processed / "古い.pdf"
    old.write_bytes(b"%PDF")
    os.utime(old, (0, 0))
    cfg.keep_processed_days = 1
    watcher.Watcher(cfg).cleanup()
    assert not old.exists()


def test_single_instance_lock(tmp_path):
    lock = tmp_path / "watcher.lock"
    with watcher.SingleInstance(lock):
        assert lock.exists()
        stale = watcher.SingleInstance(lock)
        stale.path.write_text("999999999")  # 存在しない PID
        with watcher.SingleInstance(lock):
            pass
    assert not lock.exists()


def test_single_instance_refuses_live_process(tmp_path):
    lock = tmp_path / "watcher.lock"
    lock.write_text(str(os.getppid()))
    with pytest.raises(RuntimeError, match="既に動いています"):
        with watcher.SingleInstance(lock):
            pass


# ----------------------------------------------------------------------
# 印刷ダイアログ
# ----------------------------------------------------------------------
def test_dialog_mode_launches_without_blocking(cfg, tmp_path, monkeypatch):
    """output_mode="dialog" はダイアログを起動して、待たずに戻ること。

    ここで待ってしまうと、ユーザーがダイアログを操作するまで監視が止まる。
    """
    from orihon import winprint

    launched = []
    monkeypatch.setattr(winprint, "_launch", lambda cmd, **kw: launched.append(cmd))
    cfg.output_mode = "dialog"
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")

    result = job.process_pdf(src, cfg)

    assert len(launched) == 1
    assert "printdialog" in launched[0]
    assert str(result.output) in launched[0]
    assert result.outcome is not None and "ダイアログ" in result.outcome.method


def test_dialog_prefers_sumatra_when_present(tmp_path, monkeypatch):
    from orihon import winprint

    fake = tmp_path / "SumatraPDF.exe"
    fake.write_text("")
    launched = []
    monkeypatch.setattr(winprint, "IS_WINDOWS", True)
    monkeypatch.setattr(winprint, "find_sumatra", lambda: fake)
    monkeypatch.setattr(winprint, "_launch", lambda cmd, **kw: launched.append(cmd))

    pdf = impose.write_test_pdf(tmp_path / "s.pdf", pages=1, size="A7")
    outcome = winprint.show_print_dialog(pdf)

    assert "SumatraPDF" in outcome.method
    assert launched[0][:3] == [str(fake), "-print-dialog", "-exit-when-done"]


def test_dialog_falls_back_to_acrobat(tmp_path, monkeypatch):
    from orihon import winprint

    fake = tmp_path / "AcroRd32.exe"
    fake.write_text("")
    launched = []
    monkeypatch.setattr(winprint, "IS_WINDOWS", True)
    monkeypatch.setattr(winprint, "find_sumatra", lambda: None)
    monkeypatch.setattr(winprint, "find_acrobat", lambda: fake)
    monkeypatch.setattr(winprint, "_launch", lambda cmd, **kw: launched.append(cmd))

    pdf = impose.write_test_pdf(tmp_path / "s.pdf", pages=1, size="A7")
    outcome = winprint.show_print_dialog(pdf)

    assert "Acrobat" in outcome.method
    assert launched[0] == [str(fake), "/p", "/h", str(pdf)]


def test_dialog_rejects_missing_pdf(tmp_path):
    from orihon import winprint

    with pytest.raises(winprint.PrintError, match="見つかりません"):
        winprint.show_print_dialog(tmp_path / "ない.pdf")


def test_fallback_dialog_command_is_importable(tmp_path):
    """内蔵ダイアログを別プロセスで起動するコマンドが実際に import できること。"""
    import subprocess
    import sys

    from orihon import winprint

    pdf = impose.write_test_pdf(tmp_path / "s.pdf", pages=1, size="A7")
    cmd = winprint._fallback_dialog_command(pdf)
    env, cwd = winprint._fallback_dialog_env()
    # tkinter が無い環境では「開くだけ」に落ちて 1 を返す。落ちなければ十分。
    proc = subprocess.run([sys.executable] + cmd[1:], env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode in (0, 1), proc.stderr
    assert "Traceback" not in proc.stderr


def test_open_file_never_raises(tmp_path, monkeypatch):
    from orihon import winprint

    def boom(*_a, **_k):
        raise OSError("ビューアがありません")

    monkeypatch.setattr(winprint.subprocess, "run", boom)
    monkeypatch.setattr(winprint.os, "startfile", boom, raising=False)
    outcome = winprint.open_file(tmp_path / "どこかの.pdf")
    assert outcome.method == "開けず"
