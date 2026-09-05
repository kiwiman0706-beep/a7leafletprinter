"""1 件の印刷ジョブ（元 PDF 1 個）を処理するパイプライン。

面付け → 出力（開く／実プリンタへ送る／保存だけ）までを担当する。
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from . import impose, winprint
from .config import Config

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_stem(name: str) -> str:
    stem = Path(name).name
    # "job.pdf.1234.orihon-processing" のような一時名から素の名前を取り出す
    for _ in range(4):
        root, dot, _ext = stem.rpartition(".")
        if not dot:
            break
        stem = root
    stem = _UNSAFE.sub("_", stem).strip(" .")
    return stem[:80] or "orihon"


def document_title(pdf: Path) -> str:
    """PDF のタイトル情報を取り出す。

    Microsoft Print to PDF は印刷元アプリのドキュメント名をタイトルに入れるので、
    これを出力ファイル名に使うと「どの原稿から作った折本か」が分かりやすい。
    """
    try:
        with pymupdf.open(pdf) as doc:
            title = (doc.metadata or {}).get("title") or ""
    except Exception as exc:  # pragma: no cover - 壊れた PDF など
        logger.debug("タイトルを読めませんでした: %s: %s", pdf, exc)
        return ""
    title = _UNSAFE.sub("_", title).strip(" .")
    return title[:80]


def build_output_path(
    cfg: Config, source: Path, layout_name: str, display_name: str | None = None
) -> Path:
    """設定のテンプレートから出力ファイル名を組み立てる。"""
    now = _dt.datetime.now()
    stem = _safe_stem(display_name or source.name)
    title = document_title(source) or stem
    try:
        name = cfg.filename_template.format(
            stem=stem,
            title=title,
            layout=layout_name,
            timestamp=now.strftime("%Y%m%d-%H%M%S"),
            date=now.strftime("%Y%m%d"),
            time=now.strftime("%H%M%S"),
        )
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning("filename_template が不正です（既定に戻します）: %s", exc)
        name = f"{title}_{layout_name}_{now:%Y%m%d-%H%M%S}.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    out_dir = cfg.resolved_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / _UNSAFE.sub("_", name)
    # 同名があれば連番を振る
    if path.exists():
        base, suffix = path.stem, path.suffix
        for i in range(2, 1000):
            candidate = path.with_name(f"{base}({i}){suffix}")
            if not candidate.exists():
                return candidate
    return path


@dataclass
class JobResult:
    """1 ジョブの処理結果。"""

    source: Path
    output: Path
    impose_result: impose.ImposeResult
    outcome: winprint.PrintOutcome | None
    kept_source: Path | None = None

    def summary(self) -> str:
        lines = [self.impose_result.describe()]
        if self.outcome:
            lines.append(f"出力動作   : {self.outcome}")
        if self.kept_source:
            lines.append(f"元PDF保存  : {self.kept_source}")
        return "\n".join(lines)


def process_pdf(
    source: str | Path, cfg: Config, display_name: str | None = None
) -> JobResult:
    """PDF を 1 件処理する（面付けして、設定どおりに出力する）。

    ``display_name`` にはスプールに届いたときの元のファイル名を渡す
    （監視側が一時名にリネームしてから呼ぶため）。
    """
    source = Path(source)
    layout_name = cfg.impose_options().resolved_layout().name
    output = build_output_path(cfg, source, layout_name, display_name)

    result = impose.impose_pdf(source, output, cfg.impose_options())

    outcome: winprint.PrintOutcome | None = None
    if cfg.output_mode == "print":
        try:
            outcome = winprint.print_pdf(output, cfg.target_printer)
        except winprint.PrintError as exc:
            logger.error("印刷に失敗しました: %s", exc)
            outcome = winprint.PrintOutcome("印刷失敗", str(exc))
    elif cfg.output_mode == "dialog":
        try:
            outcome = winprint.show_print_dialog(output, cfg.target_printer)
        except (winprint.PrintError, OSError) as exc:
            logger.error("印刷ダイアログを出せませんでした: %s", exc)
            outcome = winprint.PrintOutcome("ダイアログ失敗", str(exc))
    elif cfg.output_mode == "open":
        try:
            outcome = winprint.open_file(output)
        except OSError as exc:
            logger.error("PDF を開けませんでした: %s", exc)
            outcome = winprint.PrintOutcome("開けず", str(exc))
    else:
        outcome = winprint.PrintOutcome("保存のみ", str(output))

    kept: Path | None = None
    if cfg.keep_source:
        kept_dir = cfg.processed_dir()
        kept_dir.mkdir(parents=True, exist_ok=True)
        kept = kept_dir / f"{output.stem}_source.pdf"
        try:
            shutil.copy2(source, kept)
        except OSError as exc:
            logger.warning("元 PDF を保存できませんでした: %s", exc)
            kept = None

    return JobResult(
        source=source, output=output, impose_result=result, outcome=outcome, kept_source=kept
    )
