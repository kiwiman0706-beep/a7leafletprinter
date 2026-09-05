"""コマンドラインインターフェース。

    python -m orihon impose 原稿.pdf -o 折本.pdf
    python -m orihon watch
    python -m orihon gui
    python -m orihon layouts
    python -m orihon doctor
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, config, impose, layouts, watcher, winprint

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
def _add_impose_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-l", "--layout", help=f"面付けレイアウト (既定: 設定値/{layouts.DEFAULT_LAYOUT})")
    parser.add_argument("-p", "--paper", help="用紙サイズ (A4, B5, 210x297 など)")
    parser.add_argument(
        "--orientation", choices=("auto", "portrait", "landscape"), help="用紙の向き"
    )
    parser.add_argument("--margin", type=float, metavar="MM", help="各パネル内側の余白(mm)")
    parser.add_argument(
        "--guides", choices=("none", "cut", "fold", "full"),
        help="ガイド線 (none=なし / cut=切り込みのみ / fold=折り線のみ / full=図6と同じ)",
    )
    parser.add_argument("--fit", choices=("contain", "stretch"), help="パネルへの収め方")
    parser.add_argument(
        "--fill", choices=("blank", "repeat"),
        help="ページが足りないとき blank=白紙 / repeat=先頭から繰り返す",
    )
    parser.add_argument("--max-sheets", type=int, metavar="N", help="出力する用紙の最大枚数")
    parser.add_argument(
        "--numbers", action="store_true", help="確認用にパネル隅へページ番号を入れる"
    )


def _merge_impose_options(cfg: config.Config, args: argparse.Namespace) -> impose.ImposeOptions:
    opts = cfg.impose_options()
    if args.layout:
        opts.layout = args.layout
    if args.paper:
        opts.paper = args.paper
    if args.orientation:
        opts.orientation = args.orientation
    if args.margin is not None:
        opts.safe_margin_mm = args.margin
    if args.guides:
        opts.guides = args.guides
    if args.fit:
        opts.fit = args.fit
    if args.fill:
        opts.fill = args.fill
    if args.max_sheets is not None:
        opts.max_sheets = args.max_sheets
    if args.numbers:
        opts.debug_numbers = True
    return opts


# ----------------------------------------------------------------------
def cmd_impose(args: argparse.Namespace) -> int:
    cfg = config.load()
    opts = _merge_impose_options(cfg, args)
    src = Path(args.input)
    if not src.is_file():
        print(f"入力 PDF が見つかりません: {src}", file=sys.stderr)
        return 1
    out = Path(args.output) if args.output else src.with_name(f"{src.stem}_{opts.layout}.pdf")
    try:
        result = impose.impose_pdf(src, out, opts)
    except (KeyError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    print(result.describe())
    if args.print_to is not None:
        outcome = winprint.print_pdf(out, args.print_to)
        print(f"出力動作   : {outcome}")
    elif args.open:
        winprint.open_file(out)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    cfg = config.load_or_create()
    if args.spool:
        cfg.spool_dir = args.spool
    if args.once:
        watcher.setup_logging(cfg)
        w = watcher.Watcher(cfg)
        cfg.resolved_spool_dir().mkdir(parents=True, exist_ok=True)
        results = w.process_once()
        print(f"{len(results)} 件処理しました")
        return 0
    return watcher.run(cfg, console=not args.quiet)


def cmd_gui(_args: argparse.Namespace) -> int:
    from . import gui

    return gui.main()


BINDING_JA = {"left": "左綴じ（横書き向き）", "right": "右綴じ（縦書き向き）", "none": "－"}


def cmd_layouts(args: argparse.Namespace) -> int:
    for name, layout in layouts.PRESETS.items():
        print(f"[{name}] {layout.title}")
        if layout.aliases:
            print(f"  別名     : {', '.join(layout.aliases)}")
        print(f"  ページ数 : {layout.page_count} ({layout.cols}列 x {layout.rows}段)")
        print(f"  綴じ     : {BINDING_JA[layout.binding]}")
        if layout.description:
            print(f"  説明     : {layout.description}")
        if layout.source:
            print(f"  出典     : {layout.source}")
        if args.verbose or args.diagram:
            print(layout.ascii_art())
        print()
    return 0


def cmd_printers(_args: argparse.Namespace) -> int:
    printers = winprint.list_printers()
    if printers:
        default = winprint.default_printer()
        print("インストール済みプリンタ:")
        for name in printers:
            mark = " *" if name == default else ""
            print(f"  {name}{mark}")
        print("  (* = 通常使うプリンタ)")
    else:
        print("プリンタを列挙できませんでした（Windows 以外か pywin32 未導入）")
    backends = winprint.available_backends()
    print("\n使える印刷バックエンド:")
    if backends:
        for label, where in backends.items():
            print(f"  {label}: {where}")
    else:
        print("  なし（PDF は既定のビューアで開きます）")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    cfg = config.load()
    out_dir = Path(args.output_dir) if args.output_dir else cfg.resolved_output_dir() / "selftest"
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = _merge_impose_options(cfg, args)
    layout = layouts.get(opts.layout)
    src = out_dir / "テスト原稿.pdf"
    impose.write_test_pdf(src, pages=layout.page_count, size=args.page_size)
    opts.debug_numbers = True
    result = impose.impose_pdf(src, out_dir / f"テスト_{layout.name}.pdf", opts)
    print(layout.ascii_art())
    print()
    print(result.describe())
    if args.open:
        winprint.open_file(result.output)
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg = config.load()
    path = config.config_path()
    if args.set:
        for pair in args.set:
            key, sep, value = pair.partition("=")
            key = key.strip()
            if not sep:
                print(f"'キー=値' の形で指定してください: {pair}", file=sys.stderr)
                return 1
            if not hasattr(cfg, key) or key.startswith("_"):
                print(f"未知の設定キーです: {key}", file=sys.stderr)
                return 1
            current = getattr(cfg, key)
            try:
                if isinstance(current, bool):
                    coerced: object = value.strip().lower() in ("1", "true", "yes", "on", "はい")
                elif isinstance(current, int):
                    coerced = int(value)
                elif isinstance(current, float):
                    coerced = float(value)
                else:
                    coerced = value
            except ValueError:
                print(f"{key} に {value!r} は設定できません", file=sys.stderr)
                return 1
            setattr(cfg, key, coerced)
        problems = cfg.validate()
        if problems:
            for p in problems:
                print(f"設定エラー: {p}", file=sys.stderr)
            return 1
        saved = cfg.save(path)
        print(f"保存しました: {saved}")
        return 0

    print(f"# {path}{'' if path.exists() else ' (未作成・既定値)'}")
    for key, value in cfg.to_dict().items():
        print(f"{key} = {value!r}")
    print(f"\nスプール : {cfg.resolved_spool_dir()}")
    print(f"出力先   : {cfg.resolved_output_dir()}")
    print(f"ログ     : {cfg.log_dir() / 'orihon.log'}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    ok = True
    print(f"orihon {__version__}  (Python {sys.version.split()[0]}, {sys.platform})")

    try:
        import pymupdf

        print(f"[OK] PyMuPDF {pymupdf.__version__}")
    except ImportError:
        print("[NG] PyMuPDF が入っていません → pip install pymupdf")
        ok = False

    if winprint.IS_WINDOWS:
        try:
            import win32print  # noqa: F401

            print("[OK] pywin32")
        except ImportError:
            print("[--] pywin32 が無いので、プリンタ列挙は PowerShell に頼ります "
                  "→ pip install pywin32")
    else:
        print("[--] Windows ではないので、仮想プリンタ機能は使えません（面付けのみ動作します）")

    cfg = config.load()
    problems = cfg.validate()
    if problems:
        ok = False
        for p in problems:
            print(f"[NG] 設定: {p}")
    else:
        print(f"[OK] 設定 {config.config_path()}")

    for label, path in (
        ("スプール", cfg.resolved_spool_dir()),
        ("出力先", cfg.resolved_output_dir()),
        ("ログ", cfg.log_dir()),
    ):
        state = "あり" if path.is_dir() else "未作成（初回起動時に作られます）"
        print(f"[--] {label}: {path} … {state}")

    spool = cfg.resolved_spool_dir()
    stale = [f for f in spool.glob("*.pdf") if not f.name.endswith(".orihon-processing")] \
        if spool.is_dir() else []
    if stale:
        print(f"[NG] スプールに未処理の PDF が {len(stale)} 個たまっています: "
              f"{', '.join(f.name for f in stale[:3])}")
        print("     監視プロセスが動いていないと、次の印刷が失敗します "
              "（Print to PDF は既にあるファイルに書けません）。")
        print("     → 監視を開始するか、上のファイルを削除してください。")
        ok = False

    running = watcher.running_pid(cfg)
    if running:
        print(f"[OK] 監視プロセスが動いています (PID {running})")
    else:
        print("[NG] 監視プロセスが動いていません "
              "→ 「監視を開始.cmd」を実行するか、タスク OrihonPrinter Watcher を有効にしてください")
        ok = False

    printers = winprint.list_printers()
    if winprint.IS_WINDOWS:
        if config.PRINTER_NAME in printers:
            print(f"[OK] 仮想プリンタ「{config.PRINTER_NAME}」が登録されています")
        else:
            print(f"[NG] 仮想プリンタ「{config.PRINTER_NAME}」が見つかりません "
                  "→ installer\\Install-OrihonPrinter.ps1 を管理者権限で実行してください")
            ok = False
        backends = winprint.available_backends()
        print(f"[{'OK' if backends else '--'}] 印刷バックエンド: "
              + (", ".join(backends) if backends else "なし（PDF を開くだけになります）"))

    for layout in layouts.PRESETS.values():
        try:
            layout.validate()
        except layouts.LayoutError as exc:
            print(f"[NG] レイアウト {layout.name}: {exc}")
            ok = False
    print(f"[OK] レイアウト {len(layouts.PRESETS)} 種類を検証しました")
    return 0 if ok else 1


# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orihon",
        description="折本（おりほん）仮想プリンタ - PDF を折本の面付けに並べ替える",
    )
    parser.add_argument("--version", action="version", version=f"orihon {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("impose", help="PDF を面付けする")
    p.add_argument("input", help="元の PDF")
    p.add_argument("-o", "--output", help="出力 PDF（既定: 入力名_レイアウト名.pdf）")
    p.add_argument("--open", action="store_true", help="出力を既定のビューアで開く")
    p.add_argument(
        "--print-to", nargs="?", const="", metavar="PRINTER",
        help="出力をそのままプリンタへ送る（名前を省くと通常使うプリンタ）",
    )
    _add_impose_options(p)
    p.set_defaults(func=cmd_impose)

    p = sub.add_parser("watch", help="スプールフォルダを監視して自動で面付けする")
    p.add_argument("--spool", help="監視するフォルダ（既定: 設定値）")
    p.add_argument("--once", action="store_true", help="1 周だけ処理して終了する")
    p.add_argument("--quiet", action="store_true", help="コンソールにログを出さない")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("gui", help="設定画面を開く")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("layouts", help="使えるレイアウトを一覧する")
    p.add_argument("-v", "--verbose", action="store_true", help="面付け図も表示する")
    p.add_argument("--diagram", action="store_true", help="面付け図も表示する")
    p.set_defaults(func=cmd_layouts)

    p = sub.add_parser("printers", help="プリンタと印刷バックエンドを一覧する")
    p.set_defaults(func=cmd_printers)

    p = sub.add_parser("selftest", help="テスト原稿を作って面付けを確かめる")
    p.add_argument("-d", "--output-dir", help="出力先フォルダ")
    p.add_argument("--page-size", default="A7", help="テスト原稿 1 ページの用紙 (既定: A7)")
    p.add_argument("--open", action="store_true", help="結果を既定のビューアで開く")
    _add_impose_options(p)
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("config", help="設定を表示・変更する")
    p.add_argument("--set", action="append", metavar="キー=値", help="設定を書き換える")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("doctor", help="動作環境を点検する")
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (KeyError, ValueError, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
