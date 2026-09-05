"""設定ファイルの読み書き。

既定の場所は Windows なら ``%ProgramData%\\OrihonPrinter\\config.json``、
それ以外の OS では ``~/.config/orihon-printer/config.json``。
環境変数 ``ORIHON_HOME`` でデータフォルダごと差し替えられる。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

from . import impose, layouts, paper

logger = logging.getLogger(__name__)

APP_NAME = "OrihonPrinter"
PRINTER_NAME = "A7 折本プリンター"
CONFIG_FILENAME = "config.json"


def data_home() -> Path:
    """設定・スプール・ログを置くフォルダ。"""
    override = os.environ.get("ORIHON_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("ProgramData") or os.environ.get("ALLUSERSPROFILE") or "C:\\ProgramData"
        return Path(base) / APP_NAME
    return Path.home() / ".config" / "orihon-printer"


def config_path() -> Path:
    return data_home() / CONFIG_FILENAME


def default_output_dir() -> Path:
    if os.name == "nt":
        docs = Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
    else:
        docs = Path.home() / "Documents"
    return docs / APP_NAME


OutputMode = Literal["open", "dialog", "print", "save"]


@dataclass
class Config:
    """アプリ全体の設定。"""

    # --- 面付け ---
    layout: str = layouts.DEFAULT_LAYOUT
    paper: str = paper.DEFAULT_PAPER
    orientation: impose.Orientation = "auto"
    safe_margin_mm: float = 4.0
    guides: impose.Guides = "cut"
    fit: impose.Fit = "contain"
    fill: impose.FillMode = "blank"
    max_sheets: int = 0
    #: 原稿とパネルの縦横が食い違うとき、パネル内で 90 度回して余白を減らす
    auto_rotate: bool = True
    #: 原稿の周囲にある単色の帯（用紙に合わせて印刷したときの余白）を切り落とす
    trim: bool = False
    debug_numbers: bool = False

    # --- 出力 ---
    #: open=既定のビューアで開く / dialog=印刷ダイアログを出す /
    #: print=無人で実プリンタへ送る / save=保存だけ
    output_mode: OutputMode = "dialog"
    #: output_mode="print"/"dialog" のときの送り先プリンタ名（空なら通常使うプリンタ）
    target_printer: str = ""
    output_dir: str = ""
    #: 出力ファイル名のテンプレート（strftime とプレースホルダが使える）
    filename_template: str = "{title}_{layout}_{timestamp}.pdf"
    #: 面付け前の元 PDF も残す
    keep_source: bool = False

    # --- 監視 ---
    spool_dir: str = ""
    poll_interval_sec: float = 1.0
    #: 書き込み完了とみなすまでにサイズが変化しない時間
    settle_sec: float = 1.5
    #: 処理済みファイルを何日分残すか（0 で即削除）
    keep_processed_days: int = 3
    log_level: str = "INFO"

    _path: Path | None = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    def resolved_output_dir(self) -> Path:
        return Path(os.path.expandvars(self.output_dir)).expanduser() if self.output_dir else default_output_dir()

    def resolved_spool_dir(self) -> Path:
        return (
            Path(os.path.expandvars(self.spool_dir)).expanduser()
            if self.spool_dir
            else data_home() / "spool"
        )

    def processed_dir(self) -> Path:
        return data_home() / "processed"

    def log_dir(self) -> Path:
        return data_home() / "logs"

    def impose_options(self) -> impose.ImposeOptions:
        return impose.ImposeOptions(
            layout=self.layout,
            paper=self.paper,
            orientation=self.orientation,
            safe_margin_mm=self.safe_margin_mm,
            guides=self.guides,
            fit=self.fit,
            fill=self.fill,
            max_sheets=self.max_sheets,
            auto_rotate=self.auto_rotate,
            trim=self.trim,
            debug_numbers=self.debug_numbers,
        )

    def validate(self) -> list[str]:
        """設定を検証し、問題があればメッセージのリストを返す。"""
        problems: list[str] = []
        try:
            layouts.get(self.layout)
        except KeyError as exc:
            problems.append(str(exc))
        try:
            paper.get(self.paper)
        except KeyError as exc:
            problems.append(str(exc))
        if self.orientation not in ("auto", "portrait", "landscape"):
            problems.append(f"orientation が不正です: {self.orientation!r}")
        if self.guides not in ("none", "cut", "fold", "full"):
            problems.append(f"guides が不正です: {self.guides!r}")
        if self.fit not in ("contain", "stretch"):
            problems.append(f"fit が不正です: {self.fit!r}")
        if self.fill not in ("blank", "repeat"):
            problems.append(f"fill が不正です: {self.fill!r}")
        if self.output_mode not in ("open", "dialog", "print", "save"):
            problems.append(f"output_mode が不正です: {self.output_mode!r}")
        if self.safe_margin_mm < 0:
            problems.append("safe_margin_mm は 0 以上にしてください")
        if self.poll_interval_sec <= 0:
            problems.append("poll_interval_sec は 0 より大きくしてください")
        return problems

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("_path", None)
        return data

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else (self._path or config_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, target)
        object.__setattr__(self, "_path", target)
        return target


_FIELD_NAMES = {f.name for f in fields(Config) if not f.name.startswith("_")}


def from_dict(data: dict[str, Any]) -> Config:
    unknown = set(data) - _FIELD_NAMES
    if unknown:
        logger.warning("設定に未知のキーがあります（無視します）: %s", ", ".join(sorted(unknown)))
    return Config(**{k: v for k, v in data.items() if k in _FIELD_NAMES})


def load(path: str | Path | None = None) -> Config:
    """設定を読み込む。ファイルが無ければ既定値を返す。"""
    target = Path(path) if path else config_path()
    if not target.exists():
        cfg = Config()
        cfg._path = target
        return cfg
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("設定ファイルを読めませんでした（既定値を使います）: %s: %s", target, exc)
        cfg = Config()
        cfg._path = target
        return cfg
    cfg = from_dict(data)
    cfg._path = target
    return cfg


def load_or_create(path: str | Path | None = None) -> Config:
    target = Path(path) if path else config_path()
    cfg = load(target)
    if not target.exists():
        try:
            cfg.save(target)
        except OSError as exc:  # 権限が無い場所ならメモリ上の既定値のまま続行
            logger.warning("設定ファイルを作成できませんでした: %s: %s", target, exc)
    return cfg
