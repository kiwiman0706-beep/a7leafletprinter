"""折本（おりほん）仮想プリンタ。

アプリが「A7 折本プリンター」に印刷した PDF を受け取り、キンコーズの
「折本の作り方」図6 と同じ面付けに並べ替えて、実プリンタへ送る中間ドライバー。
"""

#: このパッケージの唯一のバージョン定義。
#: pyproject.toml はここを参照し、インストーラと自動更新もここを見る。
__version__ = "0.2.0"

#: 自動更新の取得元（GitHub の owner/repo）
UPDATE_REPO = "kiwiman0706-beep/a7leafletprinter"


def configure_stdio() -> None:
    """標準出力・標準エラーを UTF-8 で書けるようにする。

    Windows では、出力をファイルやパイプにリダイレクトすると、
    その環境のコードページ（英語版なら cp1252）でエンコードしようとして
    日本語のメッセージが UnicodeEncodeError になる。
    コンソールに直接出す分には問題ないので気づきにくいが、
    `orihon layouts > layouts.txt` のような使い方で落ちてしまう。

    エラー処理を backslashreplace にしてあるので、UTF-8 にできない
    環境でも（読みにくくはなるが）落ちることはない。
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            # pytest の capsys など reconfigure を持たない差し替えでは何もしない
            pass


__all__ = ["__version__", "UPDATE_REPO", "configure_stdio"]
