"""自動更新の検証（すべてネットワークを使わずにモックで行う）。"""

import io
import json
import zipfile
from pathlib import Path

import pytest

from orihon import update
from orihon.update import Release, UpdateError


# ----------------------------------------------------------------------
# バージョン比較
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.2.3", ((1, 2, 3), "")),
        ("v1.2.3", ((1, 2, 3), "")),
        ("0.1", ((0, 1), "")),
        ("1.0.0-rc1", ((1, 0, 0), "rc1")),
        ("こわれてる", ((), "")),
        ("", ((), "")),
    ],
)
def test_parse_version(text, expected):
    assert update.parse_version(text) == expected


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        ("0.2.0", "0.1.0", True),
        ("0.1.1", "0.1.0", True),
        ("1.0.0", "0.9.9", True),
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.2.0", False),
        ("0.1", "0.1.0", False),          # 0.1 と 0.1.0 は同じ
        ("0.1.0", "0.1", False),
        ("1.0.0", "1.0.0-rc1", True),     # 正式版はプレリリースより新しい
        ("1.0.0-rc1", "1.0.0", False),
        ("こわれてる", "0.1.0", False),    # 読めないものは「新しくない」
        ("0.1.0", "こわれてる", True),
    ],
)
def test_is_newer(candidate, current, expected):
    assert update.is_newer(candidate, current) is expected


# ----------------------------------------------------------------------
# リリース情報の取得
# ----------------------------------------------------------------------
def _api_payload(**overrides):
    data = {
        "tag_name": "v9.9.9",
        "name": "テストリリース",
        "body": "変更点いろいろ",
        "published_at": "2026-09-05T00:00:00Z",
        "zipball_url": "https://api.github.com/repos/x/y/zipball/v9.9.9",
        "html_url": "https://github.com/x/y/releases/tag/v9.9.9",
        "assets": [],
    }
    data.update(overrides)
    return data


def test_fetch_latest_reads_the_api(monkeypatch):
    monkeypatch.setattr(update, "_fetch_json", lambda url, timeout=15.0: _api_payload())
    release = update.fetch_latest("owner/repo")
    assert release is not None
    assert (release.version, release.tag) == ("9.9.9", "v9.9.9")
    assert release.zip_url.endswith("/zipball/v9.9.9")


def test_fetch_latest_prefers_the_attached_zip(monkeypatch):
    payload = _api_payload(assets=[
        {"name": "bootstrap.ps1", "browser_download_url": "https://example.invalid/b.ps1"},
        {"name": "orihon-printer-9.9.9.zip",
         "browser_download_url": "https://github.com/x/y/releases/download/v9.9.9/orihon-printer-9.9.9.zip"},
    ])
    monkeypatch.setattr(update, "_fetch_json", lambda url, timeout=15.0: payload)
    release = update.fetch_latest("owner/repo")
    assert release.zip_url.endswith("orihon-printer-9.9.9.zip")


def test_fetch_latest_rejects_non_https(monkeypatch):
    monkeypatch.setattr(
        update, "_fetch_json",
        lambda url, timeout=15.0: _api_payload(zipball_url="http://example.invalid/x.zip"),
    )
    with pytest.raises(UpdateError, match="https"):
        update.fetch_latest("owner/repo")


def test_fetch_latest_rejects_a_strange_repo_name():
    with pytest.raises(UpdateError, match="リポジトリ名"):
        update.fetch_latest("https://evil.invalid/x")


def test_fetch_latest_reports_network_trouble(monkeypatch):
    import urllib.error

    def boom(url, timeout=15.0):
        raise urllib.error.URLError("つながりません")

    monkeypatch.setattr(update, "_fetch_json", boom)
    with pytest.raises(UpdateError, match="つながりません"):
        update.fetch_latest("owner/repo")


def test_check_distinguishes_failure_from_up_to_date(tmp_path, monkeypatch):
    """「確認できなかった」を「最新版です」と言わないこと。"""
    import urllib.error

    def boom(url, timeout=15.0):
        raise urllib.error.URLError("つながりません")

    monkeypatch.setattr(update, "_fetch_json", boom)
    failed = update.check_detailed(tmp_path, repo="owner/repo", current="0.1.0")
    assert failed.ok is False
    assert failed.release is None
    assert "確認できませんでした" in failed.describe()

    monkeypatch.setattr(update, "fetch_latest", lambda repo, timeout=15.0: Release(
        version="0.1.0", tag="v0.1.0", name="", notes="", published_at="",
        zip_url="https://example.test/x.zip", html_url=""))
    ok = update.check_detailed(tmp_path, repo="owner/repo", current="0.1.0", force=True)
    assert ok.ok is True and ok.release is None
    assert "最新版" in ok.describe("0.1.0")


def test_check_failure_is_not_cached(tmp_path, monkeypatch):
    """失敗を「確認済み」として覚えてしまわないこと。"""
    import urllib.error

    monkeypatch.setattr(update, "_fetch_json", lambda url, timeout=15.0: (_ for _ in ()).throw(
        urllib.error.URLError("つながりません")))
    update.check_detailed(tmp_path, repo="owner/repo", current="0.1.0")
    assert not update.cache_path(tmp_path).exists()


def test_fetch_latest_handles_no_releases_yet(monkeypatch):
    import urllib.error

    def not_found(url, timeout=15.0):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))

    monkeypatch.setattr(update, "_fetch_json", not_found)
    assert update.fetch_latest("owner/repo") is None


def test_fetch_latest_reports_rate_limit_as_an_error(monkeypatch):
    import urllib.error

    def limited(url, timeout=15.0):
        raise urllib.error.HTTPError(url, 403, "rate limited", {}, io.BytesIO(b""))

    monkeypatch.setattr(update, "_fetch_json", limited)
    with pytest.raises(UpdateError, match="拒否"):
        update.fetch_latest("owner/repo")


# ----------------------------------------------------------------------
# 確認とキャッシュ
# ----------------------------------------------------------------------
def test_check_reports_a_newer_version(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "fetch_latest", lambda repo, timeout=15.0: Release(
        version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
        zip_url="https://example.test/x.zip", html_url=""))
    release = update.check(tmp_path, current="0.1.0")
    assert release is not None and release.version == "9.9.9"
    assert update.cache_path(tmp_path).exists()


def test_check_is_quiet_when_up_to_date(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "fetch_latest", lambda repo, timeout=15.0: Release(
        version="0.1.0", tag="v0.1.0", name="", notes="", published_at="",
        zip_url="https://example.test/x.zip", html_url=""))
    assert update.check(tmp_path, current="0.1.0") is None


def test_check_uses_the_cache_and_does_not_hit_the_network(tmp_path, monkeypatch):
    calls = []

    def counted(repo, timeout=15.0):
        calls.append(repo)
        return Release(version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
                       zip_url="https://example.test/x.zip", html_url="")

    monkeypatch.setattr(update, "fetch_latest", counted)
    assert update.check(tmp_path, current="0.1.0") is not None
    assert update.check(tmp_path, current="0.1.0") is not None   # 2 回目はキャッシュ
    assert len(calls) == 1
    assert update.check(tmp_path, current="0.1.0", force=True) is not None
    assert len(calls) == 2


def test_check_survives_a_broken_cache(tmp_path, monkeypatch):
    update.cache_path(tmp_path).write_text("{ こわれている", encoding="utf-8")
    monkeypatch.setattr(update, "fetch_latest", lambda repo, timeout=15.0: None)
    assert update.check(tmp_path, current="0.1.0") is None


# ----------------------------------------------------------------------
# 展開の安全性
# ----------------------------------------------------------------------
def _zip_with(entries: dict[str, str], path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return path


def test_extract_rejects_paths_escaping_the_archive(tmp_path):
    bad = _zip_with({"pkg/ok.txt": "ok", "pkg/../../evil.txt": "bad"}, tmp_path / "bad.zip")
    with zipfile.ZipFile(bad) as archive:
        with pytest.raises(UpdateError, match="不正なパス"):
            update._safe_extract(archive, tmp_path / "out")


def test_extract_rejects_absolute_paths(tmp_path):
    bad = _zip_with({"pkg/ok.txt": "ok", "/etc/evil": "bad"}, tmp_path / "bad.zip")
    with zipfile.ZipFile(bad) as archive:
        with pytest.raises(UpdateError, match="不正なパス"):
            update._safe_extract(archive, tmp_path / "out")


def test_extract_rejects_multiple_top_level_folders(tmp_path):
    bad = _zip_with({"a/x.txt": "x", "b/y.txt": "y"}, tmp_path / "bad.zip")
    with zipfile.ZipFile(bad) as archive:
        with pytest.raises(UpdateError, match="構造が想定と違います"):
            update._safe_extract(archive, tmp_path / "out")


# ----------------------------------------------------------------------
# 入れ替え
# ----------------------------------------------------------------------
def _fake_release_zip(path: Path, version: str, root_name: str = "orihon-printer-new") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{root_name}/src/orihon/__init__.py",
            f'__version__ = "{version}"\nUPDATE_REPO = "x/y"\n',
        )
        archive.writestr(f"{root_name}/src/orihon/newfile.py", "# 新しく増えたファイル\n")
        archive.writestr(f"{root_name}/installer/Install-OrihonPrinter.ps1", "# installer\n")
        archive.writestr(f"{root_name}/README.md", f"# orihon {version}\n")
        archive.writestr(f"{root_name}/pyproject.toml", "[project]\n")
    return path


@pytest.fixture()
def install_target(tmp_path):
    """更新先に見立てたフォルダ（今の版が入っている状態）。"""
    root = tmp_path / "app"
    (root / "src" / "orihon").mkdir(parents=True)
    (root / "src" / "orihon" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    (root / "installer").mkdir()
    (root / "installer" / "Install-OrihonPrinter.ps1").write_text("# old\n", encoding="utf-8")
    (root / "README.md").write_text("# old\n", encoding="utf-8")
    return root


@pytest.fixture()
def release_with_zip(tmp_path, monkeypatch):
    """ネットワークの代わりにローカルの ZIP を返すようにする。"""
    source = _fake_release_zip(tmp_path / "release.zip", "9.9.9")

    def fake_download(url, dest, timeout=120.0):
        Path(dest).write_bytes(source.read_bytes())
        return Path(dest)

    monkeypatch.setattr(update, "_download", fake_download)
    return Release(version="9.9.9", tag="v9.9.9", name="新版", notes="",
                   published_at="", zip_url="https://example.test/x.zip", html_url="")


def test_install_replaces_the_files(install_target, release_with_zip, tmp_path):
    home = tmp_path / "home"
    result = update.install(release_with_zip, home, root=install_target)

    assert result.installed is True
    assert result.to_version == "9.9.9"
    assert '"9.9.9"' in (install_target / "src" / "orihon" / "__init__.py").read_text(encoding="utf-8")
    assert (install_target / "src" / "orihon" / "newfile.py").is_file()
    assert (install_target / "README.md").read_text(encoding="utf-8").strip() == "# orihon 9.9.9"


def test_install_makes_a_backup_first(install_target, release_with_zip, tmp_path):
    home = tmp_path / "home"
    result = update.install(release_with_zip, home, root=install_target)

    assert result.backup is not None and result.backup.is_file()
    with zipfile.ZipFile(result.backup) as archive:
        names = archive.namelist()
    assert "src/orihon/__init__.py" in names
    assert '__version__ = "0.1.0"' in zipfile.ZipFile(result.backup).read(
        "src/orihon/__init__.py").decode("utf-8")


def test_install_can_skip_the_backup(install_target, release_with_zip, tmp_path):
    result = update.install(release_with_zip, tmp_path / "home", root=install_target, backup=False)
    assert result.backup is None


def test_dry_run_changes_nothing(install_target, release_with_zip, tmp_path):
    before = (install_target / "src" / "orihon" / "__init__.py").read_text(encoding="utf-8")
    result = update.install(release_with_zip, tmp_path / "home", root=install_target, dry_run=True)

    assert result.installed is False and result.dry_run is True
    assert result.to_version == "9.9.9"
    assert (install_target / "src" / "orihon" / "__init__.py").read_text(encoding="utf-8") == before
    assert not (install_target / "src" / "orihon" / "newfile.py").exists()


def test_install_keeps_files_it_does_not_know_about(install_target, release_with_zip, tmp_path):
    """設定やログを巻き添えで消さないこと。"""
    keep = install_target / "私のメモ.txt"
    keep.write_text("消さないで", encoding="utf-8")
    update.install(release_with_zip, tmp_path / "home", root=install_target)
    assert keep.read_text(encoding="utf-8") == "消さないで"


def test_install_rejects_a_wrong_target(tmp_path, release_with_zip):
    empty = tmp_path / "からっぽ"
    empty.mkdir()
    with pytest.raises(UpdateError, match="インストール先が見つかりません"):
        update.install(release_with_zip, tmp_path / "home", root=empty)


def test_install_rejects_an_archive_without_the_package(install_target, tmp_path, monkeypatch):
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("something/readme.txt", "中身がちがう")

    monkeypatch.setattr(
        update, "_download",
        lambda url, dest, timeout=120.0: (Path(dest).write_bytes(broken.read_bytes()), Path(dest))[1],
    )
    release = Release(version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
                      zip_url="https://example.test/x.zip", html_url="")
    with pytest.raises(UpdateError, match="src/orihon/__init__.py がありません"):
        update.install(release, tmp_path / "home", root=install_target)


def test_install_rejects_a_version_mismatch(install_target, tmp_path, monkeypatch):
    """リリース情報と中身のバージョンが食い違う ZIP を拒む。"""
    mismatched = _fake_release_zip(tmp_path / "mismatch.zip", "0.0.1")
    monkeypatch.setattr(
        update, "_download",
        lambda url, dest, timeout=120.0: (Path(dest).write_bytes(mismatched.read_bytes()), Path(dest))[1],
    )
    release = Release(version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
                      zip_url="https://example.test/x.zip", html_url="")
    with pytest.raises(UpdateError, match="食い違います"):
        update.install(release, tmp_path / "home", root=install_target)


def test_install_rejects_a_corrupt_zip(install_target, tmp_path, monkeypatch):
    monkeypatch.setattr(
        update, "_download",
        lambda url, dest, timeout=120.0: (Path(dest).write_bytes("これは ZIP ではない".encode("utf-8")), Path(dest))[1],
    )
    release = Release(version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
                      zip_url="https://example.test/x.zip", html_url="")
    with pytest.raises(UpdateError, match="展開できませんでした"):
        update.install(release, tmp_path / "home", root=install_target)


# ----------------------------------------------------------------------
# 監視プロセスとの連携
# ----------------------------------------------------------------------
def test_watcher_only_notifies_by_default(tmp_path, monkeypatch):
    from orihon import config, watcher

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    cfg = config.Config(update_check=True, update_auto_install=False)
    installed = []
    monkeypatch.setattr(update, "check_detailed", lambda *a, **k: update.CheckResult(
        release=Release(version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
                        zip_url="https://example.test/x.zip", html_url="")))
    monkeypatch.setattr(update, "install", lambda *a, **k: installed.append(1))

    release = watcher.Watcher(cfg).check_for_update()
    assert release is not None and installed == []


def test_watcher_installs_when_asked(tmp_path, monkeypatch):
    from orihon import config, watcher

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    cfg = config.Config(update_check=True, update_auto_install=True)
    monkeypatch.setattr(update, "check_detailed", lambda *a, **k: update.CheckResult(
        release=Release(version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
                        zip_url="https://example.test/x.zip", html_url="")))
    monkeypatch.setattr(update, "install", lambda *a, **k: update.InstallResult(
        release=a[0], installed=True, from_version="0.1.0", to_version="9.9.9",
        message="更新しました"))
    monkeypatch.setattr(update, "restart_watcher", lambda *a, **k: True)

    w = watcher.Watcher(cfg)
    w.check_for_update()
    assert w._stop is True     # 新しい版で動き直すため自分を止める


def test_watcher_ignores_update_failures(tmp_path, monkeypatch):
    from orihon import config, watcher

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    cfg = config.Config(update_check=True)

    monkeypatch.setattr(update, "check_detailed",
                        lambda *a, **k: update.CheckResult(error="つながりません"))
    assert watcher.Watcher(cfg).check_for_update() is None


def test_update_check_can_be_disabled(tmp_path, monkeypatch):
    from orihon import config, watcher

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    called = []
    monkeypatch.setattr(update, "check_detailed", lambda *a, **k: called.append(1))
    cfg = config.Config(update_check=False)
    assert watcher.Watcher(cfg).check_for_update() is None
    assert called == []


# ----------------------------------------------------------------------
# コマンドライン
# ----------------------------------------------------------------------
def test_cli_update_check_reports_a_new_version(tmp_path, monkeypatch, capsys):
    from orihon import cli

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(update, "check_detailed", lambda *a, **k: update.CheckResult(
        release=Release(
            version="9.9.9", tag="v9.9.9", name="新版", notes="・なにか直した",
            published_at="2026-09-05T00:00:00Z",
            zip_url="https://example.test/x.zip",
            html_url="https://github.com/x/y/releases/tag/v9.9.9")))

    assert cli.main(["update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "新しいバージョン" in out and "9.9.9" in out
    assert "・なにか直した" in out


def test_cli_update_says_when_up_to_date(tmp_path, monkeypatch, capsys):
    from orihon import cli

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(update, "check_detailed", lambda *a, **k: update.CheckResult())
    assert cli.main(["update", "--check"]) == 0
    assert "最新版" in capsys.readouterr().out


def test_cli_update_does_not_claim_up_to_date_when_it_could_not_check(
    tmp_path, monkeypatch, capsys
):
    from orihon import cli

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(update, "check_detailed",
                        lambda *a, **k: update.CheckResult(error="つながりません"))
    assert cli.main(["update", "--check"]) == 1
    captured = capsys.readouterr()
    assert "確認できませんでした" in captured.err
    assert "最新版" not in captured.out


def test_cli_update_dry_run(tmp_path, monkeypatch, capsys):
    from orihon import cli

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    release = Release(version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
                      zip_url="https://example.test/x.zip", html_url="")
    monkeypatch.setattr(update, "check_detailed",
                        lambda *a, **k: update.CheckResult(release=release))
    monkeypatch.setattr(update, "install", lambda *a, **k: update.InstallResult(
        release=release, installed=False, from_version="0.1.0", to_version="9.9.9",
        dry_run=True, message="0.1.0 → 9.9.9 に更新できます"))

    assert cli.main(["update", "--dry-run", "--yes"]) == 0
    assert "更新できます" in capsys.readouterr().out


def test_cli_update_reports_failures(tmp_path, monkeypatch, capsys):
    from orihon import cli

    monkeypatch.setenv("ORIHON_HOME", str(tmp_path / "home"))
    release = Release(version="9.9.9", tag="v9.9.9", name="", notes="", published_at="",
                      zip_url="https://example.test/x.zip", html_url="")
    monkeypatch.setattr(update, "check_detailed",
                        lambda *a, **k: update.CheckResult(release=release))

    def boom(*a, **k):
        raise UpdateError("書き込めません")

    monkeypatch.setattr(update, "install", boom)
    assert cli.main(["update", "--yes"]) == 1
    assert "書き込めません" in capsys.readouterr().err


def test_restart_watcher_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(update.os, "name", "posix")
    assert update.restart_watcher() is False


def test_cache_round_trip(tmp_path):
    update._write_cache(tmp_path, {"checked_at": 1.0, "latest": None})
    assert update._read_cache(tmp_path)["checked_at"] == 1.0
    assert json.loads(update.cache_path(tmp_path).read_text(encoding="utf-8"))["latest"] is None
