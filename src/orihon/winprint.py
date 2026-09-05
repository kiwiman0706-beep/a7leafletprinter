"""Windows のプリンタ操作（一覧取得と PDF の実プリンタ送出）。

PDF を「無人で」印刷する標準 API は Windows に無いため、使える手段を
上から順に試す:

1. SumatraPDF      … ``-print-to`` が最も素直で速い
2. Ghostscript     … ``mswinpr2`` デバイス経由
3. PDFtoPrinter    … 単体 exe の定番ツール
4. ShellExecute    … 既定の PDF ビューアの "printto" 動詞（送り先指定可）
5. 既定ビューアで開く（＝ユーザーが手で印刷）

Windows 以外では 5 だけが動く。

「印刷ダイアログを出してユーザーに選ばせる」場合は ``show_print_dialog()`` を
使う。こちらは無人印刷とちがって**ユーザーの操作を待つ**ので、呼び出し側を
止めないように常に非同期（プロセスを起動して即座に戻る）で動く。
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
_ACROBAT_CANDIDATES = (
    r"%ProgramFiles%\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
    r"%ProgramFiles%\Adobe\Acrobat\Acrobat\Acrobat.exe",
    r"%ProgramFiles(x86)%\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
    r"%ProgramFiles(x86)%\Adobe\Reader 11.0\Reader\AcroRd32.exe",
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


def find_acrobat() -> Path | None:
    return find_tool(("AcroRd32", "Acrobat.exe"), _ACROBAT_CANDIDATES)


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


# ----------------------------------------------------------------------
# 印刷ダイアログを出す（ユーザーが送り先・部数・両面などを選ぶ）
# ----------------------------------------------------------------------
def _launch(cmd: list[str], **kwargs: object) -> None:
    """対話的なプロセスを起動して、待たずに戻る。

    印刷ダイアログはユーザーの操作を待つので、``subprocess.run`` で待つと
    監視ループが最大数分止まってしまう。必ず起動しっぱなしにする。
    """
    logger.debug("launch: %s", cmd)
    subprocess.Popen(cmd, creationflags=_NO_WINDOW, **kwargs)  # noqa: S603


def _fallback_dialog_command(pdf: Path) -> list[str]:
    """自前のプリンタ選択ダイアログを別プロセスで開くコマンドを組み立てる。

    別プロセスにするのは 2 つの理由から:
    tkinter はメインスレッドでしか動かせない（監視はスレッドで回っている）ことと、
    ダイアログの応答を待つ間も監視を続けたいこと。
    """
    exe = Path(sys.executable)
    if os.name == "nt":
        # コンソールを出さない pythonw.exe があればそちらを使う
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.is_file():
            exe = pythonw
    return [str(exe), "-m", "orihon", "printdialog", str(pdf)]


def _fallback_dialog_env() -> tuple[dict[str, str], str]:
    """別プロセスから orihon を import できる環境変数と作業フォルダ。"""
    src_dir = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing}" if existing else str(src_dir)
    return env, str(src_dir)


def dialog_backends() -> dict[str, str]:
    """印刷ダイアログを出せる手段と、その実行ファイルの場所。"""
    out: dict[str, str] = {}
    exe = find_sumatra()
    if exe:
        out["SumatraPDF"] = str(exe)
    exe = find_acrobat()
    if exe:
        out["Adobe Acrobat/Reader"] = str(exe)
    out["orihon 内蔵のプリンタ選択ダイアログ"] = "同梱"
    return out


def show_print_dialog(pdf: str | Path, prefer_printer: str = "") -> PrintOutcome:
    """PDF を開いて Windows の印刷ダイアログを出す。

    無人印刷とちがい、送り先・部数・両面・拡大縮小をユーザーが選べる。
    使える手段を上から順に試す:

    1. SumatraPDF ``-print-dialog`` … Windows 本来の印刷ダイアログがそのまま出る
    2. Adobe Acrobat / Reader ``/p``  … 同上
    3. orihon 内蔵のダイアログ        … プリンタと部数だけを選んで送る

    どれも即座に戻る（ユーザーの操作は待たない）。
    """
    pdf = Path(pdf)
    if not pdf.is_file():
        raise PrintError(f"PDF が見つかりません: {pdf}")

    errors: list[str] = []

    if IS_WINDOWS:
        exe = find_sumatra()
        if exe:
            try:
                _launch([str(exe), "-print-dialog", "-exit-when-done", str(pdf)])
                return PrintOutcome("SumatraPDF の印刷ダイアログ", str(pdf))
            except OSError as exc:
                errors.append(f"SumatraPDF: {exc}")

        exe = find_acrobat()
        if exe:
            try:
                _launch([str(exe), "/p", "/h", str(pdf)])
                return PrintOutcome("Acrobat の印刷ダイアログ", str(pdf))
            except OSError as exc:
                errors.append(f"Acrobat: {exc}")

    # 3. 内蔵ダイアログ（Windows 以外でも動く）
    try:
        env, cwd = _fallback_dialog_env()
        _launch(_fallback_dialog_command(pdf), env=env, cwd=cwd)
        return PrintOutcome("プリンタ選択ダイアログ", str(pdf))
    except OSError as exc:
        errors.append(f"内蔵ダイアログ: {exc}")

    logger.warning("印刷ダイアログを出せませんでした: %s", " | ".join(errors))
    open_file(pdf)
    return PrintOutcome("開く（ダイアログを出せず）", f"{pdf} / {' | '.join(errors)}")


def open_file(path: Path) -> PrintOutcome:
    """既定のアプリでファイルを開く。

    開けなかった場合も例外は投げず、失敗を表す ``PrintOutcome`` を返す。
    これは最後の受け皿なので、ここで落ちると呼び出し側が軒並み道連れになる。
    """
    path = Path(path)
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as exc:
        logger.warning("ファイルを開けませんでした: %s: %s", path, exc)
        return PrintOutcome("開けず", f"{path}: {exc}")
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
