"""設定画面（Tkinter）。

追加ライブラリ無しで動くように、標準の tkinter だけで作ってある。

    python -m orihon gui
"""

from __future__ import annotations

import logging
import queue
import threading
import traceback
from pathlib import Path
from typing import Any

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover - tkinter 無し環境
    raise SystemExit(
        "tkinter が使えません。Windows 版 Python なら標準で入っています。\n"
        f"詳細: {exc}"
    ) from None

from . import config, impose, job, layouts, paper, watcher, winprint

logger = logging.getLogger(__name__)

GUIDE_CHOICES = [
    ("cut", "切り込みだけ引く（おすすめ）"),
    ("full", "折り線も全部引く（図6と同じ）"),
    ("fold", "折り線だけ引く"),
    ("none", "何も引かない"),
]
FIT_CHOICES = [("contain", "縦横比を保って収める"), ("stretch", "パネルいっぱいに引き伸ばす")]
FILL_CHOICES = [("blank", "白紙で埋める"), ("repeat", "先頭ページから繰り返す")]
ORIENTATION_CHOICES = [("auto", "自動"), ("portrait", "縦"), ("landscape", "横")]
OUTPUT_CHOICES = [
    ("dialog", "PDF を開いて印刷ダイアログを出す（おすすめ）"),
    ("open", "PDF ビューアで開くだけ"),
    ("print", "確認なしでそのままプリンタへ送る"),
    ("save", "フォルダに保存するだけ"),
]


def _combo(parent: tk.Misc, values: list[tuple[str, str]], var: tk.StringVar) -> ttk.Combobox:
    labels = [label for _, label in values]
    box = ttk.Combobox(parent, values=labels, state="readonly", textvariable=var, width=32)
    return box


class OrihonApp:
    """設定画面と監視の起動・停止をまとめたウィンドウ。"""

    def __init__(self, root: tk.Tk, cfg: config.Config) -> None:
        self.root = root
        self.cfg = cfg
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.watcher: watcher.Watcher | None = None
        self.thread: threading.Thread | None = None

        root.title(f"{config.PRINTER_NAME} - 設定")
        root.minsize(720, 560)

        self._build_vars()
        self._build_widgets()
        self._sync_layout_preview()
        self.root.after(200, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _build_vars(self) -> None:
        c = self.cfg
        self.v_layout = tk.StringVar(value=self._layout_label(c.layout))
        self.v_paper = tk.StringVar(value=c.paper)
        self.v_orientation = tk.StringVar(value=_label_for(ORIENTATION_CHOICES, c.orientation))
        self.v_margin = tk.StringVar(value=f"{c.safe_margin_mm:g}")
        self.v_guides = tk.StringVar(value=_label_for(GUIDE_CHOICES, c.guides))
        self.v_fit = tk.StringVar(value=_label_for(FIT_CHOICES, c.fit))
        self.v_fill = tk.StringVar(value=_label_for(FILL_CHOICES, c.fill))
        self.v_auto_rotate = tk.BooleanVar(value=c.auto_rotate)
        self.v_trim = tk.BooleanVar(value=c.trim)
        self.v_numbers = tk.BooleanVar(value=c.debug_numbers)
        self.v_output_mode = tk.StringVar(value=_label_for(OUTPUT_CHOICES, c.output_mode))
        self.v_printer = tk.StringVar(value=c.target_printer)
        self.v_output_dir = tk.StringVar(value=str(c.resolved_output_dir()))
        self.v_keep_source = tk.BooleanVar(value=c.keep_source)
        self.v_status = tk.StringVar(value="停止中")

    @staticmethod
    def _layout_label(name: str) -> str:
        try:
            layout = layouts.get(name)
        except KeyError:
            layout = layouts.get(layouts.DEFAULT_LAYOUT)
        return f"{layout.title}  [{layout.name}]"

    def _layout_name(self) -> str:
        label = self.v_layout.get()
        if "[" in label and label.endswith("]"):
            return label[label.rindex("[") + 1 : -1]
        return layouts.DEFAULT_LAYOUT

    # ------------------------------------------------------------------
    def _build_widgets(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        note = ttk.Label(
            outer,
            text=(
                f"アプリの印刷ダイアログで「{config.PRINTER_NAME}」を選ぶと、"
                "ここでの設定どおりに面付けした PDF が作られます。"
            ),
            wraplength=680,
            foreground="#334",
        )
        note.pack(anchor="w", pady=(0, 10))

        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)
        nb.add(self._tab_layout(nb), text="面付け")
        nb.add(self._tab_output(nb), text="出力")
        nb.add(self._tab_watch(nb), text="監視")

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="保存", command=self.save).pack(side="left")
        ttk.Button(bar, text="テスト出力", command=self.test_output).pack(side="left", padx=6)
        ttk.Button(bar, text="出力フォルダを開く", command=self.open_output_dir).pack(side="left")
        ttk.Button(bar, text="ログを開く", command=self.open_log).pack(side="left", padx=6)
        ttk.Button(bar, text="閉じる", command=self._on_close).pack(side="right")

    # -- タブ: 面付け --------------------------------------------------
    def _tab_layout(self, parent: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)
        grid = ttk.Frame(frame)
        grid.pack(fill="x")

        labels = [self._layout_label(n) for n in layouts.names()]
        ttk.Label(grid, text="レイアウト").grid(row=0, column=0, sticky="w", pady=4)
        box = ttk.Combobox(grid, values=labels, state="readonly",
                           textvariable=self.v_layout, width=42)
        box.grid(row=0, column=1, sticky="w", pady=4)
        box.bind("<<ComboboxSelected>>", lambda _e: self._sync_layout_preview())

        ttk.Label(grid, text="用紙").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(grid, values=paper.names(), textvariable=self.v_paper,
                     width=20).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(grid, text="用紙の向き").grid(row=2, column=0, sticky="w", pady=4)
        _combo(grid, ORIENTATION_CHOICES, self.v_orientation).grid(
            row=2, column=1, sticky="w", pady=4)

        ttk.Label(grid, text="パネル内側の余白 (mm)").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(grid, textvariable=self.v_margin, width=8).grid(
            row=3, column=1, sticky="w", pady=4)

        ttk.Label(grid, text="ガイド線").grid(row=4, column=0, sticky="w", pady=4)
        _combo(grid, GUIDE_CHOICES, self.v_guides).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(grid, text="パネルへの収め方").grid(row=5, column=0, sticky="w", pady=4)
        _combo(grid, FIT_CHOICES, self.v_fit).grid(row=5, column=1, sticky="w", pady=4)

        ttk.Label(grid, text="ページが足りないとき").grid(row=6, column=0, sticky="w", pady=4)
        _combo(grid, FILL_CHOICES, self.v_fill).grid(row=6, column=1, sticky="w", pady=4)

        ttk.Checkbutton(
            grid, text="横長の原稿はパネル内で90度回して余白を減らす",
            variable=self.v_auto_rotate,
        ).grid(row=7, column=1, sticky="w", pady=4)
        ttk.Checkbutton(
            grid, text="原稿の周りの余白（単色の帯）を切り落とす",
            variable=self.v_trim,
        ).grid(row=8, column=1, sticky="w", pady=4)
        ttk.Checkbutton(grid, text="確認用にページ番号を入れる",
                        variable=self.v_numbers).grid(row=9, column=1, sticky="w", pady=4)

        ttk.Separator(frame).pack(fill="x", pady=10)
        ttk.Label(frame, text="面付け図（^ = そのまま / v = 180度回転 / === = 切り込み）").pack(anchor="w")
        self.preview = tk.Text(frame, height=10, width=64, font=("Consolas", 10),
                               relief="flat", background="#f7f7f9")
        self.preview.pack(fill="both", expand=True, pady=(6, 0))
        self.preview.configure(state="disabled")
        return frame

    # -- タブ: 出力 ----------------------------------------------------
    def _tab_output(self, parent: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)

        ttk.Label(frame, text="面付けした PDF をどうするか").grid(
            row=0, column=0, sticky="w", pady=4)
        _combo(frame, OUTPUT_CHOICES, self.v_output_mode).grid(
            row=0, column=1, sticky="w", pady=4, columnspan=2)

        ttk.Label(frame, text="送り先プリンタ").grid(row=1, column=0, sticky="w", pady=4)
        printers = [p for p in winprint.list_printers() if p != config.PRINTER_NAME]
        combo = ttk.Combobox(frame, values=[""] + printers,
                             textvariable=self.v_printer, width=42)
        combo.grid(row=1, column=1, sticky="w", pady=4, columnspan=2)
        default = winprint.default_printer()
        ttk.Label(
            frame,
            text=("空欄なら通常使うプリンタ"
                  + (f"（現在: {default}）" if default else "")),
            foreground="#666",
        ).grid(row=2, column=1, sticky="w")

        ttk.Label(frame, text="出力フォルダ").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.v_output_dir, width=44).grid(
            row=3, column=1, sticky="w", pady=4)
        ttk.Button(frame, text="参照...", command=self._pick_output_dir).grid(
            row=3, column=2, sticky="w", padx=6)

        ttk.Checkbutton(frame, text="面付け前の元 PDF も残す",
                        variable=self.v_keep_source).grid(row=4, column=1, sticky="w", pady=6)

        backends = winprint.available_backends()
        text = "印刷ダイアログ: " + ", ".join(winprint.dialog_backends()) + "\n"
        text += ("無人印刷: " + ", ".join(backends)) if backends else (
            "無人印刷できるツールが見つかりません。"
            "SumatraPDF か Ghostscript を入れると「確認なしで送る」が使えます。"
        )
        ttk.Label(frame, text=text, foreground="#666", wraplength=620).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))
        return frame

    # -- タブ: 監視 ----------------------------------------------------
    def _tab_watch(self, parent: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)
        ttk.Label(frame, text=f"スプールフォルダ: {self.cfg.resolved_spool_dir()}").pack(anchor="w")
        ttk.Label(frame, text=f"ログ: {self.cfg.log_dir() / 'orihon.log'}").pack(anchor="w", pady=(2, 10))

        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.btn_start = ttk.Button(bar, text="監視を開始", command=self.start_watch)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="監視を停止", command=self.stop_watch, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Label(bar, textvariable=self.v_status).pack(side="left", padx=12)

        ttk.Label(frame, text="処理ログ").pack(anchor="w", pady=(12, 4))
        self.logbox = tk.Text(frame, height=14, font=("Consolas", 9),
                              relief="flat", background="#f7f7f9")
        self.logbox.pack(fill="both", expand=True)
        self.logbox.configure(state="disabled")
        self._log("設定画面を開きました。")
        self._log(
            "常駐させたい場合は installer\\Install-OrihonPrinter.ps1 が作る"
            "ログオン時タスクを使ってください。"
        )
        return frame

    # ------------------------------------------------------------------
    def _sync_layout_preview(self) -> None:
        layout = layouts.get(self._layout_name())
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", f"{layout.title}\n\n{layout.ascii_art()}\n\n{layout.description}")
        self.preview.configure(state="disabled")

    def _log(self, text: str) -> None:
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text.rstrip() + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _pick_output_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.v_output_dir.get() or None)
        if chosen:
            self.v_output_dir.set(chosen)

    # ------------------------------------------------------------------
    def collect(self) -> config.Config | None:
        """画面の内容を Config に取り込む。問題があれば None。"""
        cfg = self.cfg
        cfg.layout = self._layout_name()
        cfg.paper = self.v_paper.get().strip() or paper.DEFAULT_PAPER
        cfg.orientation = _value_for(ORIENTATION_CHOICES, self.v_orientation.get())  # type: ignore[assignment]
        try:
            cfg.safe_margin_mm = float(self.v_margin.get())
        except ValueError:
            messagebox.showerror("設定エラー", "余白は数値で入力してください。")
            return None
        cfg.guides = _value_for(GUIDE_CHOICES, self.v_guides.get())  # type: ignore[assignment]
        cfg.fit = _value_for(FIT_CHOICES, self.v_fit.get())  # type: ignore[assignment]
        cfg.fill = _value_for(FILL_CHOICES, self.v_fill.get())  # type: ignore[assignment]
        cfg.auto_rotate = bool(self.v_auto_rotate.get())
        cfg.trim = bool(self.v_trim.get())
        cfg.debug_numbers = bool(self.v_numbers.get())
        cfg.output_mode = _value_for(OUTPUT_CHOICES, self.v_output_mode.get())  # type: ignore[assignment]
        cfg.target_printer = self.v_printer.get().strip()
        cfg.output_dir = self.v_output_dir.get().strip()
        cfg.keep_source = bool(self.v_keep_source.get())

        problems = cfg.validate()
        if problems:
            messagebox.showerror("設定エラー", "\n".join(problems))
            return None
        return cfg

    def save(self) -> None:
        cfg = self.collect()
        if cfg is None:
            return
        try:
            path = cfg.save()
        except OSError as exc:
            messagebox.showerror("保存できません", str(exc))
            return
        self._log(f"設定を保存しました: {path}")
        messagebox.showinfo("保存しました", f"設定を保存しました。\n{path}")

    def test_output(self) -> None:
        cfg = self.collect()
        if cfg is None:
            return
        layout = layouts.get(cfg.layout)
        out_dir = cfg.resolved_output_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            src = out_dir / "テスト原稿.pdf"
            impose.write_test_pdf(src, pages=layout.page_count, size="A7")
            opts = cfg.impose_options()
            opts.debug_numbers = True
            result = impose.impose_pdf(src, out_dir / f"テスト_{layout.name}.pdf", opts)
            winprint.open_file(result.output)
        except Exception as exc:
            logger.exception("テスト出力に失敗しました")
            messagebox.showerror("テスト出力に失敗しました", f"{exc}\n\n{traceback.format_exc()}")
            return
        self._log(f"テスト出力: {result.output}")

    def open_output_dir(self) -> None:
        path = Path(self.v_output_dir.get() or self.cfg.resolved_output_dir())
        path.mkdir(parents=True, exist_ok=True)
        winprint.open_file(path)

    def open_log(self) -> None:
        log_file = self.cfg.log_dir() / "orihon.log"
        if not log_file.exists():
            messagebox.showinfo("ログ", "まだログがありません。")
            return
        winprint.open_file(log_file)

    # ------------------------------------------------------------------
    def start_watch(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        cfg = self.collect()
        if cfg is None:
            return
        other = watcher.running_pid(cfg)
        if other is not None and not messagebox.askokcancel(
            "監視プロセスが動いています",
            f"別の監視プロセス (PID {other}) が既に同じフォルダを見ています。\n"
            "ログオン時タスクとして常駐している可能性があります。\n\n"
            "それでもこの画面から監視を始めますか？",
        ):
            return
        self.watcher = watcher.Watcher(
            cfg,
            on_job=lambda r: self.events.put(("job", r)),
            on_error=lambda p, e: self.events.put(("error", (p, e))),
        )
        self.thread = threading.Thread(target=self._run_watch, daemon=True)
        self.thread.start()
        self.v_status.set("監視中")
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._log(f"監視を開始しました: {cfg.resolved_spool_dir()}")

    def _run_watch(self) -> None:
        try:
            assert self.watcher is not None
            self.watcher.run()
        except Exception as exc:  # pragma: no cover - スレッド内
            self.events.put(("fatal", exc))
        finally:
            self.events.put(("stopped", None))

    def stop_watch(self) -> None:
        if self.watcher:
            self.watcher.stop()
        self.v_status.set("停止処理中...")
        self.btn_stop.configure(state="disabled")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "job":
                    result: job.JobResult = payload
                    self._log(
                        f"面付けしました: {result.output.name} "
                        f"({result.impose_result.sheets} 枚 / {result.outcome})"
                    )
                elif kind == "error":
                    path, exc = payload
                    self._log(f"失敗: {Path(path).name}: {exc}")
                elif kind == "fatal":
                    self._log(f"監視が異常終了しました: {payload}")
                elif kind == "stopped":
                    self.v_status.set("停止中")
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self._log("監視を停止しました。")
        except queue.Empty:
            pass
        self.root.after(200, self._drain_events)

    def _on_close(self) -> None:
        if self.thread and self.thread.is_alive():
            if not messagebox.askokcancel("終了", "監視中です。停止して閉じますか？"):
                return
            self.stop_watch()
            self.thread.join(timeout=3)
        self.root.destroy()


def _label_for(choices: list[tuple[str, str]], value: str) -> str:
    for key, label in choices:
        if key == value:
            return label
    return choices[0][1]


def _value_for(choices: list[tuple[str, str]], label: str) -> str:
    for key, text in choices:
        if text == label:
            return key
    return choices[0][0]


def main() -> int:
    cfg = config.load_or_create()
    watcher.setup_logging(cfg, to_console=False)
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except tk.TclError:  # pragma: no cover - 環境依存
        pass
    OrihonApp(root, cfg)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
