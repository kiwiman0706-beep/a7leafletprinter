"""Windows のプリンタ操作（一覧取得と PDF の実プリンタ送出）。

PDF を「無人で」印刷する標準 API は Windows に無いため、使える手段を
上から順に試す:

1. SumatraPDF      … ``-print-to`` が最も素直で速い
2. Ghostscript     … ``mswinpr2`` デバイス経由
3. PDFtoPrinter    … 単体 exe の定番ツール
4. ShellExecute    … 既定の PDF ビューアの "printto" 動詞（送り先指定可）
5. 既定ビューアで開く（＝ユーザーが手で印刷）

Windows 以外では 5 だけが動く。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

IS_WINDOWS = os.name == "nt"

#: 生成した Windows 用サブプロセスにコンソールを出さない
_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

_SUMATRA_CANDIDATES = (
    r"%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe",
    r"%ProgramFiles%\SumatraPDF\SumatraPDF.exe",
    r"%ProgramFiles(x86)%\SumatraPDF\SumatraPDF.exe",
)
_GS_CANDIDATES = (
    r"%ProgramFiles%\gs\*\bin\gswin64c.exe",
    r"%ProgramFiles(x86)%\gs\*\bin\gswin32c.exe",
)
_PDFTOPRINTER_CANDIDATES = (
    r"%LOCALAPPDATA%\PDFtoPrinter\PDFtoPrinter.exe",
    r"%ProgramFiles%\PDFtoPrinter\PDFtoPrinter.exe",
)


class PrintError(RuntimeError):
    """印刷に失敗したときに送出される。"""


@dataclass(frozen=True)
class PrintOutcome:
    """印刷（または代替動作）の結果。"""

    method: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.method}: {self.detail}" if self.detail else self.method


# ----------------------------------------------------------------------
# プリンタ一覧
# ----------------------------------------------------------------------
def list_printers() -> list[str]:
    """インストール済みプリンタ名の一覧。Windows 以外では空。"""
    if not IS_WINDOWS:
        return []
    try:
        import win32print  # type: ignore
    except ImportError:
        logger.debug("pywin32 が無いため PowerShell でプリンタを列挙します")
        return _list_printers_powershell()
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        return [p[2] for p in win32print.EnumPrinters(flags, None, 1)]
    except Exception as exc:  # pragma: no cover - 環境依存
        logger.warning("EnumPrinters に失敗しました: %s", exc)
        return _list_printers_powershell()


def _list_printers_powershell() -> list[str]:  # pragma: no cover - Windows 専用
    if not IS_WINDOWS:
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Printer | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Get-Printer に失敗しました: %s", exc)
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def default_printer() -> str:
    """通常使うプリンタの名前。取得できなければ空文字。"""
    if not IS_WINDOWS:
        return ""
    try:
        import win32print  # type: ignore

        return win32print.GetDefaultPrinter()
    except Exception:  # pragma: no cover - 環境依存
        return ""


# ----------------------------------------------------------------------
# 外部ツールの探索
# ----------------------------------------------------------------------
def _expand(pattern: str) -> list[Path]:
    expanded = os.path.expandvars(pattern)
    if "%" in expanded:  # 展開できない環境変数が残っている
        return []
    if "*" in expanded:
        root = Path(expanded).parts[0]
        try:
            return sorted(Path(root).glob(str(Path(expanded).relative_to(root))))
        except (OSError, ValueError):
            return []
    path = Path(expanded)
    return [path] if path.is_file() else []


def find_tool(exe_names: tuple[str, ...], candidates: tuple[str, ...]) -> Path | None:
    for name in exe_names:
        found = shutil.which(name)
        if found:
            return Path(found)
    for pattern in candidates:
        for path in _expand(pattern):
            if path.is_file():
                return path
    return None


def find_sumatra() -> Path | None:
    return find_tool(("SumatraPDF", "SumatraPDF.exe"), _SUMATRA_CANDIDATES)


def find_ghostscript() -> Path | None:
    return find_tool(("gswin64c", "gswin32c", "gs"), _GS_CANDIDATES)


def find_pdftoprinter() -> Path | None:
    return find_tool(("PDFtoPrinter", "PDFtoPrinter.exe"), _PDFTOPRINTER_CANDIDATES)


def available_backends() -> dict[str, str]:
    """使える印刷バックエンドと、その実行ファイルの場所。"""
    out: dict[str, str] = {}
    for label, finder in (
        ("SumatraPDF", find_sumatra),
        ("Ghostscript", find_ghostscript),
        ("PDFtoPrinter", find_pdftoprinter),
    ):
        path = finder()
        if path:
            out[label] = str(path)
    if IS_WINDOWS:
        out.setdefault("ShellExecute(printto)", "Windows 標準")
    return out


# ----------------------------------------------------------------------
# 印刷
# ----------------------------------------------------------------------
def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    logger.debug("run: %s", cmd)
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW
    )


def _print_with_sumatra(pdf: Path, printer: str, exe: Path) -> PrintOutcome:
    cmd = [str(exe), "-print-to", printer] if printer else [str(exe), "-print-to-default"]
    cmd += ["-silent", "-exit-when-done", str(pdf)]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise PrintError(f"SumatraPDF が失敗しました (rc={proc.returncode}): {proc.stderr.strip()}")
    return PrintOutcome("SumatraPDF", printer or "既定のプリンタ")


def _print_with_ghostscript(pdf: Path, printer: str, exe: Path,
                            extra_args: list[str] | None = None) -> PrintOutcome:
    cmd = [
        str(exe), "-dPrinted", "-dBATCH", "-dNOPAUSE", "-dNOSAFER", "-dQUIET",
        "-dNumCopies=1", "-sDEVICE=mswinpr2",
    ]
    if printer:
        cmd.append(f"-sOutputFile=%printer%{printer}")
    cmd += list(extra_args or [])
    cmd.append(str(pdf))
    proc = _run(cmd)
    if proc.returncode != 0:
        raise PrintError(f"Ghostscript が失敗しました (rc={proc.returncode}): {proc.stderr.strip()}")
    return PrintOutcome("Ghostscript", printer or "既定のプリンタ")


def _print_with_pdftoprinter(pdf: Path, printer: str, exe: Path) -> PrintOutcome:
    cmd = [str(exe), str(pdf)] + ([printer] if printer else [])
    proc = _run(cmd)
    if proc.returncode != 0:
        raise PrintError(f"PDFtoPrinter が失敗しました (rc={proc.returncode}): {proc.stderr.strip()}")
    return PrintOutcome("PDFtoPrinter", printer or "既定のプリンタ")


def _print_with_shell(pdf: Path, printer: str) -> PrintOutcome:  # pragma: no cover - Windows 専用
    if not IS_WINDOWS:
        raise PrintError("ShellExecute は Windows でのみ使えます")
    try:
        import win32api  # type: ignore
    except ImportError as exc:
        raise PrintError("pywin32 が入っていないため ShellExecute を使えません") from exc
    verb, params = ("printto", f'"{printer}"') if printer else ("print", None)
    try:
        win32api.ShellExecute(0, verb, str(pdf), params, str(pdf.parent), 0)
    except Exception as exc:
        raise PrintError(f"ShellExecute({verb}) に失敗しました: {exc}") from exc
    return PrintOutcome(f"ShellExecute({verb})", printer or "既定のプリンタ")


def open_file(path: Path) -> PrintOutcome:
    """既定のアプリでファイルを開く。"""
    path = Path(path)
    if IS_WINDOWS:
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)
    return PrintOutcome("開く", str(path))


def print_pdf(
    pdf: str | Path,
    printer: str = "",
    *,
    fallback_open: bool = True,
    gs_extra_args: list[str] | None = None,
) -> PrintOutcome:
    """PDF を実プリンタへ送る。

    使えるバックエンドを順に試し、どれも駄目なら（``fallback_open`` が真なら）
    既定のビューアで開いてユーザーに手で印刷してもらう。
    """
    pdf = Path(pdf)
    if not pdf.is_file():
        raise PrintError(f"PDF が見つかりません: {pdf}")

    errors: list[str] = []

    if IS_WINDOWS:
        strategies = []
        exe = find_sumatra()
        if exe:
            strategies.append(lambda e=exe: _print_with_sumatra(pdf, printer, e))
        exe = find_ghostscript()
        if exe:
            strategies.append(lambda e=exe: _print_with_ghostscript(pdf, printer, e, gs_extra_args))
        exe = find_pdftoprinter()
        if exe:
            strategies.append(lambda e=exe: _print_with_pdftoprinter(pdf, printer, e))
        strategies.append(lambda: _print_with_shell(pdf, printer))

        for strategy in strategies:
            try:
                outcome = strategy()
                logger.info("印刷しました: %s", outcome)
                return outcome
            except (PrintError, OSError, subprocess.SubprocessError) as exc:
                errors.append(str(exc))
                logger.warning("印刷バックエンドが失敗しました: %s", exc)
    else:
        errors.append("Windows 以外では自動印刷に対応していません")

    if fallback_open:
        logger.info("自動印刷できなかったので既定のビューアで開きます")
        outcome = open_file(pdf)
        return PrintOutcome(
            "開く（自動印刷できず）",
            f"{pdf} / 試した結果: " + " | ".join(errors) if errors else str(pdf),
        )
    raise PrintError("印刷に失敗しました: " + " | ".join(errors))
