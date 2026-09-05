"""GitHub のリリースを見て、新しい版があれば知らせる／入れ替える。

方針
----
* 取得元は ``orihon.UPDATE_REPO`` に固定した GitHub リポジトリのみ。
  設定で別のリポジトリに向けることもできるが、既定値から変えない限り
  ほかの場所からコードを取ってくることはない。
* **既定では「知らせるだけ」**。実際に入れ替えるのは、設定で
  ``update_auto_install`` を有効にするか ``orihon update`` を明示的に
  実行したときだけ。
* 入れ替える前に必ず現在のファイルを ZIP でバックアップする。
* 展開先を検査し、アーカイブの外へ書き出そうとするパス（zip slip）は拒否する。

ネットワークは標準ライブラリの ``urllib`` だけで済ませている（追加依存なし）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import UPDATE_REPO, __version__

logger = logging.getLogger(__name__)

API_TEMPLATE = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = f"orihon-printer/{__version__}"
CACHE_FILENAME = "update-cache.json"
BACKUP_DIRNAME = "backups"

#: 更新で入れ替える対象。ここに無いものには触らない（設定やログを消さないため）
UPDATABLE = ("src", "installer", "tools", "docs")
UPDATABLE_FILES = (
    "README.md", "CHANGELOG.md", "LICENSE",
    "pyproject.toml", "requirements.txt", ".gitattributes",
)

#: リポジトリ名として受け付ける形（任意の URL を踏まないための最低限の検査）
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-.]?([0-9A-Za-z.-]+))?$")


class UpdateError(RuntimeError):
    """更新処理が続けられないときに送出される。"""


# ----------------------------------------------------------------------
# バージョン比較
# ----------------------------------------------------------------------
def parse_version(text: str) -> tuple[tuple[int, ...], str]:
    """``v1.2.3-rc1`` を ``((1, 2, 3), "rc1")`` に分解する。"""
    match = _VERSION_RE.match((text or "").strip())
    if not match:
        return (), ""
    numbers = tuple(int(part) for part in match.group(1).split("."))
    return numbers, (match.group(2) or "")


def is_newer(candidate: str, current: str) -> bool:
    """``candidate`` が ``current`` より新しければ True。

    数字の部分だけで比べ、``1.2`` と ``1.2.0`` は同じ扱いにする。
    プレリリース（``1.0.0-rc1``）は同じ数字の正式版より古いとみなす。
    """
    cand_nums, cand_pre = parse_version(candidate)
    cur_nums, cur_pre = parse_version(current)
    if not cand_nums:
        return False
    if not cur_nums:
        return True
    length = max(len(cand_nums), len(cur_nums))
    cand_padded = cand_nums + (0,) * (length - len(cand_nums))
    cur_padded = cur_nums + (0,) * (length - len(cur_nums))
    if cand_padded != cur_padded:
        return cand_padded > cur_padded
    # 数字が同じならプレリリースの有無で決める（無いほうが新しい）
    return bool(cur_pre) and not cand_pre


# ----------------------------------------------------------------------
# リリース情報
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Release:
    """GitHub のリリース 1 件。"""

    version: str
    tag: str
    name: str
    notes: str
    published_at: str
    zip_url: str
    html_url: str

    @property
    def summary(self) -> str:
        head = f"{self.name or self.tag}（{self.version}）"
        if self.published_at:
            head += f"  {self.published_at[:10]}"
        return head


def _fetch_json(url: str, timeout: float = 15.0) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, dest: Path, timeout: float = 120.0) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        with dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    return dest


def fetch_latest(repo: str = UPDATE_REPO, timeout: float = 15.0) -> Release | None:
    """GitHub から最新リリースを取ってくる。取れなければ None。"""
    if not _REPO_RE.match(repo or ""):
        raise UpdateError(f"取得元のリポジトリ名が不正です: {repo!r}")
    url = API_TEMPLATE.format(repo=repo)
    try:
        data = _fetch_json(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.info("まだリリースがありません: %s", repo)
            return None
        if exc.code in (403, 429):
            raise UpdateError(
                "GitHub へのアクセスを拒否されました（API の回数制限か、"
                "ネットワーク側の制限かもしれません）"
            ) from exc
        raise UpdateError(f"リリース情報を取得できませんでした: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"GitHub につながりませんでした: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateError(f"リリース情報を解釈できませんでした: {exc}") from exc

    tag = str(data.get("tag_name") or "")
    if not tag:
        return None

    # リリースに配布用 ZIP が添付されていればそちらを使う。
    # 無ければ GitHub が自動生成する zipball を使う。
    zip_url = ""
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if name.startswith("orihon-printer") and name.endswith(".zip"):
            zip_url = str(asset.get("browser_download_url") or "")
            break
    zip_url = zip_url or str(data.get("zipball_url") or "")
    if not zip_url.startswith("https://"):
        raise UpdateError(f"配布ファイルの URL が https ではありません: {zip_url!r}")
    return Release(
        version=tag.lstrip("vV"),
        tag=tag,
        name=str(data.get("name") or ""),
        notes=str(data.get("body") or ""),
        published_at=str(data.get("published_at") or ""),
        zip_url=zip_url,
        html_url=str(data.get("html_url") or ""),
    )


# ----------------------------------------------------------------------
# 確認結果のキャッシュ（API を叩きすぎないため）
# ----------------------------------------------------------------------
def cache_path(home: Path) -> Path:
    return home / CACHE_FILENAME


def _read_cache(home: Path) -> dict:
    try:
        return json.loads(cache_path(home).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(home: Path, data: dict) -> None:
    try:
        home.mkdir(parents=True, exist_ok=True)
        cache_path(home).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.debug("更新キャッシュを書けませんでした: %s", exc)


@dataclass(frozen=True)
class CheckResult:
    """更新確認の結果。

    「新しい版が無かった」のか「そもそも確認できなかった」のかを
    呼び出し側が区別できるようにしている。
    """

    release: Release | None = None
    from_cache: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        """確認そのものができたか（新しい版の有無とは別）。"""
        return not self.error

    @property
    def has_update(self) -> bool:
        return self.release is not None

    def describe(self, current: str = __version__) -> str:
        if self.error:
            return f"確認できませんでした（{self.error}）"
        if self.release:
            return f"新しいバージョンがあります: {self.release.summary}"
        return f"最新版です（{current}）"


def check_detailed(
    home: Path,
    repo: str = UPDATE_REPO,
    current: str = __version__,
    interval_hours: float = 24.0,
    force: bool = False,
) -> CheckResult:
    """新しい版があるか確かめ、結果を ``CheckResult`` で返す。

    ``interval_hours`` 以内に確認済みならキャッシュを使い、通信しない。
    """
    cache = _read_cache(home)
    now = time.time()
    if not force and (now - float(cache.get("checked_at", 0))) < interval_hours * 3600:
        cached = cache.get("latest")
        if not cached:
            return CheckResult(from_cache=True)
        release = Release(**cached)
        return CheckResult(
            release=release if is_newer(release.version, current) else None,
            from_cache=True,
        )

    try:
        release = fetch_latest(repo)
    except UpdateError as exc:
        logger.warning("更新の確認に失敗しました: %s", exc)
        return CheckResult(error=str(exc))

    _write_cache(
        home,
        {
            "checked_at": now,
            "checked_at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "current": current,
            "latest": release.__dict__ if release else None,
        },
    )
    if release and is_newer(release.version, current):
        return CheckResult(release=release)
    return CheckResult()


def check(
    home: Path,
    repo: str = UPDATE_REPO,
    current: str = __version__,
    interval_hours: float = 24.0,
    force: bool = False,
) -> Release | None:
    """新しい版があれば ``Release`` を、無ければ（確認できなくても）None を返す。"""
    return check_detailed(home, repo, current, interval_hours, force).release


# ----------------------------------------------------------------------
# 展開と入れ替え
# ----------------------------------------------------------------------
def install_root() -> Path:
    """このパッケージが置かれているリポジトリのルート（``src`` の親）。"""
    return Path(__file__).resolve().parents[2]


def _safe_extract(archive: zipfile.ZipFile, dest: Path) -> Path:
    """ZIP を安全に展開し、中身の最上位フォルダを返す。

    アーカイブの外へ書き出そうとするパス（zip slip）は拒否する。
    """
    dest = dest.resolve()
    roots: set[str] = set()
    for info in archive.infolist():
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise UpdateError(f"配布ファイルに不正なパスが含まれています: {name!r}")
        target = (dest / name).resolve()
        if not str(target).startswith(str(dest) + os.sep) and target != dest:
            raise UpdateError(f"配布ファイルに不正なパスが含まれています: {name!r}")
        first = Path(name).parts[0] if Path(name).parts else ""
        if first:
            roots.add(first)
    if len(roots) != 1:
        raise UpdateError(f"配布ファイルの構造が想定と違います（最上位: {sorted(roots)}）")
    archive.extractall(dest)
    return dest / roots.pop()


def _extracted_version(root: Path) -> str:
    init = root / "src" / "orihon" / "__init__.py"
    if not init.is_file():
        raise UpdateError("配布ファイルに src/orihon/__init__.py がありません")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
    if not match:
        raise UpdateError("配布ファイルからバージョンを読み取れませんでした")
    return match.group(1)


def make_backup(root: Path, home: Path, version: str) -> Path:
    """入れ替え前の状態を ZIP に固めて残す。"""
    backup_dir = home / BACKUP_DIRNAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"orihon-{version}-{stamp}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in UPDATABLE:
            folder = root / name
            if not folder.is_dir():
                continue
            for item in folder.rglob("*"):
                if item.is_file() and "__pycache__" not in item.parts:
                    archive.write(item, item.relative_to(root).as_posix())
        for name in UPDATABLE_FILES:
            item = root / name
            if item.is_file():
                archive.write(item, name)
    return path


def _copy_tree(source: Path, target: Path) -> list[str]:
    """新しいファイルを上書きコピーする（余分なファイルは消さない）。"""
    changed: list[str] = []
    for name in UPDATABLE:
        src_dir = source / name
        if not src_dir.is_dir():
            continue
        for item in src_dir.rglob("*"):
            if not item.is_file():
                continue
            relative = item.relative_to(source)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            changed.append(relative.as_posix())
    for name in UPDATABLE_FILES:
        item = source / name
        if item.is_file():
            shutil.copy2(item, target / name)
            changed.append(name)
    return changed


@dataclass
class InstallResult:
    """入れ替えの結果。"""

    release: Release
    installed: bool
    from_version: str
    to_version: str
    backup: Path | None = None
    changed_files: int = 0
    dry_run: bool = False
    message: str = ""


def install(
    release: Release,
    home: Path,
    root: Path | None = None,
    *,
    dry_run: bool = False,
    backup: bool = True,
) -> InstallResult:
    """リリースをダウンロードして入れ替える。"""
    root = (root or install_root()).resolve()
    if not (root / "src" / "orihon" / "__init__.py").is_file():
        raise UpdateError(
            f"インストール先が見つかりません（{root} に src/orihon がありません）。"
            " pip でインストールした場合は pip install -U で更新してください。"
        )

    with tempfile.TemporaryDirectory(prefix="orihon-update-") as tmp:
        tmp_path = Path(tmp)
        archive_path = _download(release.zip_url, tmp_path / "release.zip")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                extracted = _safe_extract(archive, tmp_path / "extracted")
        except zipfile.BadZipFile as exc:
            raise UpdateError(f"配布ファイルを展開できませんでした: {exc}") from exc

        found = _extracted_version(extracted)
        if not is_newer(found, __version__) and found != release.version:
            raise UpdateError(
                f"配布ファイルのバージョン（{found}）がリリース（{release.version}）と食い違います"
            )

        if dry_run:
            return InstallResult(
                release=release, installed=False, from_version=__version__,
                to_version=found, dry_run=True,
                message=f"{__version__} → {found} に更新できます（--dry-run のため実行していません）",
            )

        backup_path = make_backup(root, home, __version__) if backup else None
        try:
            changed = _copy_tree(extracted, root)
        except OSError as exc:
            raise UpdateError(
                f"ファイルを書き込めませんでした: {exc}"
                + (f"（{backup_path} から戻せます）" if backup_path else "")
            ) from exc

    logger.info("更新しました: %s → %s（%d ファイル）", __version__, found, len(changed))
    return InstallResult(
        release=release, installed=True, from_version=__version__, to_version=found,
        backup=backup_path, changed_files=len(changed),
        message=f"{__version__} → {found} に更新しました",
    )


# ----------------------------------------------------------------------
# 監視プロセスの再起動
# ----------------------------------------------------------------------
TASK_NAME = "OrihonPrinter Watcher"


def restart_watcher(task_name: str = TASK_NAME, delay_sec: int = 5) -> bool:
    """更新後に監視プロセスを入れ替えるため、遅延して再起動を仕掛ける。

    自分自身が監視プロセスであることを想定しているので、
    「少し待ってからタスクを開始する」処理を切り離したプロセスに任せ、
    呼び出し側はそのあと自分で終了する。
    """
    if os.name != "nt":
        logger.info("Windows 以外なので監視プロセスの再起動は行いません")
        return False
    try:
        subprocess.Popen(  # noqa: S603
            ["cmd", "/c", f'timeout /t {delay_sec} /nobreak >nul & schtasks /Run /TN "{task_name}"'],
            creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        )
    except OSError as exc:
        logger.warning("監視プロセスの再起動を仕掛けられませんでした: %s", exc)
        return False
    logger.info("%d 秒後に「%s」を開始します", delay_sec, task_name)
    return True


def current_version() -> str:
    return __version__


def describe_environment() -> str:
    return f"orihon {__version__} ({sys.platform}, {install_root()})"
