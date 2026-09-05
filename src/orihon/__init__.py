"""折本（おりほん）仮想プリンタ。

アプリが「A7 折本プリンター」に印刷した PDF を受け取り、キンコーズの
「折本の作り方」図6 と同じ面付けに並べ替えて、実プリンタへ送る中間ドライバー。
"""

#: このパッケージの唯一のバージョン定義。
#: pyproject.toml はここを参照し、インストーラと自動更新もここを見る。
__version__ = "0.1.0"

#: 自動更新の取得元（GitHub の owner/repo）
UPDATE_REPO = "kiwiman0706-beep/a7leafletprinter"

__all__ = ["__version__", "UPDATE_REPO"]
