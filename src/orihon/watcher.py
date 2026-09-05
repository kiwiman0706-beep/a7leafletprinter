"""スプールフォルダの監視。

仮想プリンタ（Microsoft Print to PDF ＋ ローカルポート）が書き出した PDF を
拾い、面付けして出力するところまでを回し続ける。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import job
from .config import Config, load_or_create

logger = logging.getLogger(__name__)

LOCK_FILENAME = "watcher.lock"
CLAIM_SUFFIX = ".orihon-processing"


# ----------------------------------------------------------------------
# 多重起動の防止
# ----------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:  # pragma: no cover - 環境依存
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SingleInstance:
    """ロックファイルで多重起動を防ぐ。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def __enter__(self) -> "SingleInstance":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                pid = int(self.path.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                pid = 0
            if pid and pid != os.getpid() and _pid_alive(pid):
                raise RuntimeError(
                    f"監視プロセスは既に動いています (PID {pid})。"
                    f" 止めたい場合はそのプロセスを終了するか {self.path} を消してください。"
                )
            self.path.unlink(missing_ok=True)
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        self.acquired = True
        return self

    def __exit__(self, *exc: object) -> None:
        if self.acquired:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


def lock_path(cfg: Config) -> Path:
    return cfg.log_dir().parent / LOCK_FILENAME


def running_pid(cfg: Config) -> int | None:
    """既に監視プロセスが動いていればその PID を返す。"""
    path = lock_path(cfg)
    try:
        pid = int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return None
    if pid and pid != os.getpid() and _pid_alive(pid):
        return pid
    return None


# ----------------------------------------------------------------------
# ログ
# ----------------------------------------------------------------------
def setup_logging(cfg: Config, to_console: bool = True) -> Path:
    log_dir = cfg.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "orihon.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if to_console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        root.addHandler(stream)
    return log_path


# ----------------------------------------------------------------------
# 監視本体
# ----------------------------------------------------------------------
@dataclass
class _Seen:
    size: int
    since: float


class Watcher:
    """スプールフォルダを監視して、届いた PDF を処理する。"""

    def __init__(
        self,
        cfg: Config,
        on_job: Callable[[job.JobResult], None] | None = None,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_job = on_job
        self.on_error = on_error
        self._seen: dict[Path, _Seen] = {}
        self._stop = False
        self._last_cleanup = 0.0

    # -- 制御 -------------------------------------------------------
    def stop(self) -> None:
        self._stop = True

    # -- 1 周分 -----------------------------------------------------
    def candidates(self) -> list[Path]:
        spool = self.cfg.resolved_spool_dir()
        if not spool.is_dir():
            return []
        out = []
        for path in sorted(spool.iterdir()):
            if not path.is_file():
                continue
            if path.name.endswith(CLAIM_SUFFIX) or path.name == LOCK_FILENAME:
                continue
            if path.suffix.lower() not in (".pdf", ".ps", ".prn", ""):
                continue
            out.append(path)
        return out

    def _is_settled(self, path: Path, now: float) -> bool:
        """書き込みが終わったとみなせるか。

        「ポーリング間でサイズが変わらない状態が ``settle_sec`` 続いた」か、
        「最終更新から ``settle_sec`` 以上経っている」のどちらかで判定する。
        後者があるおかげで、監視を後から起動しても取りこぼさない。
        """
        try:
            stat = path.stat()
        except OSError:
            self._seen.pop(path, None)
            return False
        if stat.st_size == 0:
            self._seen[path] = _Seen(stat.st_size, now)
            return False

        settle = max(0.0, self.cfg.settle_sec)
        if (time.time() - stat.st_mtime) >= settle:
            return True

        seen = self._seen.get(path)
        if seen is None or seen.size != stat.st_size:
            self._seen[path] = _Seen(stat.st_size, now)
            return False
        return (now - seen.since) >= settle

    def _claim(self, path: Path) -> Path | None:
        """他のプロセス／スプーラが掴んでいないことを確かめつつ確保する。

        Windows では書き込み中のファイルはリネームできないので、
        リネームの成否がそのまま「書き込み完了」の判定になる。
        """
        claimed = path.with_name(f"{path.name}.{os.getpid()}{CLAIM_SUFFIX}")
        try:
            os.replace(path, claimed)
        except OSError as exc:
            logger.debug("まだ掴めません（書き込み中?） %s: %s", path.name, exc)
            return None
        self._seen.pop(path, None)
        return claimed

    def process_once(self) -> list[job.JobResult]:
        results: list[job.JobResult] = []
        now = time.monotonic()
        for path in self.candidates():
            if not self._is_settled(path, now):
                continue
            claimed = self._claim(path)
            if claimed is None:
                continue
            logger.info("ジョブを受け取りました: %s (%d bytes)", path.name, claimed.stat().st_size)
            try:
                result = job.process_pdf(claimed, self.cfg, display_name=path.name)
            except Exception as exc:  # 1 件の失敗で監視を止めない
                logger.exception("ジョブの処理に失敗しました: %s", path.name)
                self._quarantine(claimed)
                if self.on_error:
                    self.on_error(path, exc)
                continue
            logger.info("完了:\n%s", result.summary())
            results.append(result)
            if self.on_job:
                try:
                    self.on_job(result)
                except Exception:  # pragma: no cover - コールバック側の都合
                    logger.exception("on_job コールバックが失敗しました")
            try:
                claimed.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("一時ファイルを消せませんでした: %s: %s", claimed, exc)
        return results

    def _quarantine(self, claimed: Path) -> None:
        """処理に失敗した PDF を failed フォルダへ退避する。"""
        failed_dir = self.cfg.processed_dir() / "failed"
        try:
            failed_dir.mkdir(parents=True, exist_ok=True)
            target = failed_dir / f"{int(time.time())}_{claimed.name.split('.')[0]}.pdf"
            os.replace(claimed, target)
            logger.warning("失敗した PDF を退避しました: %s", target)
        except OSError as exc:
            logger.warning("失敗した PDF を退避できませんでした: %s", exc)

    def cleanup(self) -> None:
        """古い処理済みファイルを片付ける。"""
        days = self.cfg.keep_processed_days
        base = self.cfg.processed_dir()
        if not base.is_dir():
            return
        cutoff = time.time() - days * 86400
        for path in base.rglob("*.pdf"):
            try:
                if days <= 0 or path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    # -- ループ -----------------------------------------------------
    def run(self) -> None:
        spool = self.cfg.resolved_spool_dir()
        spool.mkdir(parents=True, exist_ok=True)
        self.cfg.resolved_output_dir().mkdir(parents=True, exist_ok=True)
        logger.info("監視を開始します: %s", spool)
        logger.info(
            "レイアウト=%s 用紙=%s 出力=%s%s",
            self.cfg.layout,
            self.cfg.paper,
            self.cfg.output_mode,
            f" -> {self.cfg.target_printer}" if self.cfg.target_printer else "",
        )
        while not self._stop:
            try:
                self.process_once()
                if time.monotonic() - self._last_cleanup > 3600:
                    self.cleanup()
                    self._last_cleanup = time.monotonic()
            except Exception:  # pragma: no cover - 想定外でも監視は続ける
                logger.exception("監視ループで例外が発生しました")
            time.sleep(self.cfg.poll_interval_sec)
        logger.info("監視を終了しました")


def run(cfg: Config | None = None, console: bool = True) -> int:
    """監視をブロッキングで実行する（``python -m orihon watch`` の実体）。"""
    cfg = cfg or load_or_create()
    setup_logging(cfg, to_console=console)
    problems = cfg.validate()
    if problems:
        for p in problems:
            logger.error("設定エラー: %s", p)
        return 2

    watcher = Watcher(cfg)

    def _handle(signum: int, _frame: object) -> None:
        logger.info("シグナル %s を受け取りました。終了します。", signum)
        watcher.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):  # pragma: no cover - スレッド上などでは設定できない
            pass

    try:
        with SingleInstance(lock_path(cfg)):
            watcher.run()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 3
    return 0
