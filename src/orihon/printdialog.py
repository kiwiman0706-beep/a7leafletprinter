"""orihon 内蔵のプリンタ選択ダイアログ（tkinter）。

SumatraPDF も Acrobat も見つからないときの受け皿。Windows 本来の
印刷ダイアログほど細かくは選べないが、送り先プリンタと部数は指定できる。

``winprint.show_print_dialog()`` から**別プロセスとして**起動される:

    python -m orihon printdialog 折本.pdf

tkinter はメインスレッドでしか動かせないうえ、ダイアログはユーザーの操作を
待つので、監視プロセスの中で直接開くわけにはいかない。
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import winprint

logger = logging.getLogger(__name__)

WARNING_TEXT = (
    "折り位置がずれないよう、プリンタ側の設定は\n"
    "「実際のサイズ」「拡大縮小なし（100%）」にしてください。"
)


def show(pdf: str | Path, prefer_printer: str = "") -> int:
    """ダイアログを開く。印刷したら 0、キャンセルなら 1。"""
    pdf = Path(pdf)
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError as exc:
        logger.error("tkinter が使えないので PDF を開くだけにします: %s", exc)
        winprint.open_file(pdf)
        return 1

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        # tkinter はあるが画面が無い（DISPLAY 無し、セッション 0 のサービス、
        # Tcl の導入が壊れている等）。ここで落ちると何も起きないので、
        # せめて PDF を開いてユーザーが手で印刷できるようにする。
        logger.error("画面を開けないので PDF を開くだけにします: %s", exc)
        winprint.open_file(pdf)
        return 1

    try:
        return _build_and_run(root, pdf, prefer_printer, tk, ttk, messagebox)
    except Exception as exc:  # ダイアログを出せないなら開くだけにフォールバック
        logger.exception("印刷ダイアログを組み立てられませんでした")
        try:
            root.destroy()
        except Exception:
            pass
        logger.error("PDF を開くだけにします: %s", exc)
        winprint.open_file(pdf)
        return 1


def _build_and_run(root, pdf: Path, prefer_printer: str, tk, ttk, messagebox) -> int:
    """ダイアログを組み立てて表示する（``show()`` の中身）。"""
    printers = [p for p in winprint.list_printers() if "折本" not in p]
    default = winprint.default_printer()
    initial = prefer_printer or (default if default in printers else "")
    if not initial and printers:
        initial = printers[0]

    root.title("折本を印刷")
    root.resizable(False, False)
    try:
        root.call("tk", "scaling", 1.2)
    except tk.TclError:  # pragma: no cover - 環境依存
        pass

    result = {"printed": False}
    v_printer = tk.StringVar(value=initial)
    v_copies = tk.StringVar(value="1")

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text=pdf.name, font=("", 11, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(frame, text=str(pdf.parent), foreground="#666").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

    ttk.Label(frame, text="プリンタ").grid(row=2, column=0, sticky="w", pady=4)
    if printers:
        ttk.Combobox(frame, values=printers, textvariable=v_printer,
                     state="readonly", width=40).grid(row=2, column=1, sticky="w", pady=4)
    else:
        ttk.Label(frame, text="（プリンタを列挙できませんでした。通常使うプリンタへ送ります）",
                  foreground="#a60").grid(row=2, column=1, sticky="w", pady=4)

    ttk.Label(frame, text="部数").grid(row=3, column=0, sticky="w", pady=4)
    ttk.Spinbox(frame, from_=1, to=99, textvariable=v_copies, width=6).grid(
        row=3, column=1, sticky="w", pady=4)

    ttk.Label(frame, text=WARNING_TEXT, foreground="#a4552b",
              justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def do_print() -> None:
        try:
            copies = max(1, min(99, int(v_copies.get())))
        except ValueError:
            messagebox.showerror("部数", "部数は 1〜99 の数値で入力してください。")
            return
        try:
            for _ in range(copies):
                outcome = winprint.print_pdf(pdf, v_printer.get(), fallback_open=False)
        except winprint.PrintError as exc:
            messagebox.showerror("印刷できませんでした", str(exc))
            return
        logger.info("印刷しました: %s x%d (%s)", pdf.name, copies, outcome)
        result["printed"] = True
        root.destroy()

    def do_open() -> None:
        winprint.open_file(pdf)
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(16, 0))
    ttk.Button(buttons, text="印刷", command=do_print).pack(side="right")
    ttk.Button(buttons, text="PDF を開く", command=do_open).pack(side="right", padx=6)
    ttk.Button(buttons, text="キャンセル", command=root.destroy).pack(side="right")

    root.bind("<Escape>", lambda _e: root.destroy())
    root.bind("<Return>", lambda _e: do_print())
    try:
        root.attributes("-topmost", True)
        root.after(400, lambda: root.attributes("-topmost", False))
    except tk.TclError:  # pragma: no cover - 環境依存
        pass
    root.mainloop()
    return 0 if result["printed"] else 1
