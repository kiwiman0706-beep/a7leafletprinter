# A7 折本プリンター

**Windows 用の仮想プリンタ（中間ドライバー）です。**
どんなアプリからでも「印刷 → A7 折本プリンター」を選ぶだけで、
[キンコーズ・ジャパン「手軽に作れる折本の作り方」](https://www.kinkos.co.jp/column/folding-book/)
の図6 と同じ面付けに並べ替えた PDF ができ、そのまま実際のプリンタへ流せます。

A4 用紙 1 枚・**片面印刷だけ**で、A7（74×105mm）8 ページの小冊子が作れます。

<img src="docs/images/layout-orihon8.svg" width="520" alt="A4 を 8 分割した折本の面付け図">

---

## しくみ

```
  ┌──────────┐   印刷    ┌──────────────┐  PDF   ┌──────────────┐
  │ Word / PDF │ ───────▶ │ A7 折本プリンター │ ─────▶ │ スプールフォルダ │
  │ ブラウザ 等 │          │ (Print to PDF +  │        │  job.pdf        │
  └──────────┘          │  ローカルポート)  │        └───────┬──────┘
                          └──────────────┘                │ 監視
                                                            ▼
  ┌──────────┐  印刷/表示 ┌──────────────┐  面付け  ┌──────────────┐
  │ 実プリンタ  │ ◀─────── │ 折本 PDF        │ ◀────── │ orihon watch   │
  └──────────┘            └──────────────┘          └──────────────┘
```

Windows の署名付きカーネルドライバーを書く必要はありません。
標準の **「Microsoft Print to PDF」ドライバー**を、ファイルを指す
**ローカルポート**に紐づけた仮想プリンタを作り、そこへ落ちてきた PDF を
常駐プロセスが拾って面付けし直す、という構成です。
保存ダイアログは出ないので、ユーザーから見れば「折本で刷れるプリンタ」が
1 つ増えたように見えます。

---

## インストール

### 必要なもの

| | |
|---|---|
| OS | Windows 10 / 11（「Microsoft Print to PDF」が使えること） |
| Python | 3.10 以上 |
| ライブラリ | `pymupdf`、`pywin32`（インストーラが自動で入れます） |
| 実プリンタへ自動送出したい場合 | [SumatraPDF](https://www.sumatrapdfreader.org/) または Ghostscript（任意） |

### 手順

1. このリポジトリをダウンロード（または `git clone`）します。
2. `installer\install.cmd` をダブルクリックします。
   UAC が出るので「はい」を選んでください（プリンタとポートの追加に管理者権限が要ります）。
3. 最後に環境チェックが走り、`[OK]` が並べば完了です。

```powershell
# 手動で実行する場合
powershell -ExecutionPolicy Bypass -File .\installer\Install-OrihonPrinter.ps1

# オプション例：プリンタ名と既定用紙を変える
.\installer\Install-OrihonPrinter.ps1 -PrinterName "折本プリンター" -DefaultPaper A4
```

インストーラがやること:

- `C:\ProgramData\OrihonPrinter\` 以下にスプール・ログ・設定フォルダを作る
- ローカルポート `…\spool\job.pdf` を作る
- そのポートに「Microsoft Print to PDF」を紐づけた仮想プリンタを作る
- 仮想プリンタの既定用紙を **A7** にする（`-DefaultPaper` で変更可）
- `pymupdf` / `pywin32` を pip で入れる
- 監視プロセスをログオン時に自動起動するタスク **OrihonPrinter Watcher** を登録する

### アンインストール

```powershell
.\installer\uninstall.cmd            # 設定とログは残す
# または
.\installer\Uninstall-OrihonPrinter.ps1 -RemoveData   # きれいに全部消す
```

---

## 使い方

1. 好きなアプリで原稿を開き、**印刷 → プリンタに「A7 折本プリンター」** を選びます。
   * 用紙は **A7** のまま印刷するのがいちばんきれいです（文字が縮みません）。
     A7 を選べないアプリなら A4 のままでも構いません（自動で縮小配置します）。
   * ページ数は **8 の倍数**にすると無駄がありません。足りない分は白紙になります。
2. 面付けされた PDF が `ドキュメント\OrihonPrinter\` にでき、
   既定の設定ではそのまま PDF ビューアで開きます。
3. その PDF を **A4・片面・等倍（100%／フチなしではない）** で印刷します。
4. [折り方](#折り方)のとおりに折れば折本の完成です。

設定を変えるには:

```
C:\ProgramData\OrihonPrinter\設定を開く.cmd
```

<img src="docs/images/layout-orihon4.svg" width="300" alt="A4 を 4 分割した折本の面付け図">

---

## 折り方

図6 の面付けは 8 マス（4 列 × 2 段）です。**赤い線＝ハサミを入れる場所**、
**破線＝折り線**で、どちらもレイアウト定義から自動的に導かれます。

1. 印刷した面を上にして置きます。
2. 用紙を **横半分**（上下の境目）に折って、しっかり折り目を付けてから開きます。
3. 同じように**縦に 4 等分**の折り目を付けて、開きます。
4. **中央 2 マス分の横線**（印刷された赤い線）にハサミを入れます。
   端までは切らず、中央の 2 マス分だけです。
5. もう一度用紙を横半分に折ると、切り込みが開いて穴になります。
6. 左右の端を中央に向かって押し込むと、切り込みが十字に開きます。
7. 表紙（①）が外側に来るようにたたんで、折り目を整えれば完成です。

> **なぜこの並びなのか**
> 折本は「1 枚の紙の片面だけ」で本にするので、ページ①→②→…→⑧→① が
> マスの上を一筆書きでぐるりと一周している必要があります。
> このとき、左右に隣り合うマスは向きが同じ、上下に隣り合うマスは向きが 180 度逆になります。
> 一周のつながりに使われない境界＝どこにも折れない線が「切り込み」です。
> 詳しくは [docs/layout.md](docs/layout.md) を参照してください。

---

## 設定

`C:\ProgramData\OrihonPrinter\config.json` に保存されます。
設定画面（`orihon gui`）か、コマンドラインから変更できます。

| キー | 既定値 | 説明 |
|---|---|---|
| `layout` | `orihon8` | 面付けレイアウト（後述） |
| `paper` | `A4` | 出力用紙。`B5` や `210x297` のような直接指定も可 |
| `orientation` | `auto` | 用紙の向き。`auto` は原稿の縦横比から自動判定 |
| `safe_margin_mm` | `4.0` | 各パネル内側の余白。プリンタの印字できないフチよけ |
| `guides` | `cut` | `none` / `cut`（切り込みのみ）/ `fold`（折り線のみ）/ `full`（図6 と同じ） |
| `fit` | `contain` | `contain`=縦横比を保つ / `stretch`=パネルいっぱいに伸ばす |
| `fill` | `blank` | ページが足りないとき `blank`=白紙 / `repeat`=先頭から繰り返す |
| `max_sheets` | `0` | 出力する用紙の最大枚数（0 で無制限） |
| `output_mode` | `open` | `open`=ビューアで開く / `print`=プリンタへ送る / `save`=保存だけ |
| `target_printer` | `""` | `print` のときの送り先。空なら通常使うプリンタ |
| `output_dir` | `ドキュメント\OrihonPrinter` | 出力先フォルダ |
| `filename_template` | `{title}_{layout}_{timestamp}.pdf` | `{title}` `{stem}` `{layout}` `{timestamp}` `{date}` `{time}` が使えます |
| `keep_source` | `false` | 面付け前の元 PDF も残す |
| `settle_sec` | `1.5` | この秒数だけ更新が止まったら「書き込み完了」とみなす |
| `keep_processed_days` | `3` | 処理済みファイルを残す日数 |

`{title}` は PDF のタイトル情報から取ります。Microsoft Print to PDF は
印刷元アプリのドキュメント名をここに入れるので、
「どの原稿から作った折本か」がファイル名で分かります。

---

## レイアウト一覧

`orihon layouts -v` で面付け図つきの一覧が出ます。

| 名前 | 別名 | 内容 |
|---|---|---|
| `orihon8` | `a7`, `8p` | **既定。** A4→A7 8 ページ・左綴じ（図6 と同じ） |
| `orihon8-right` | `a7-right` | 同 8 ページの右綴じ（縦書き・マンガ向け） |
| `orihon4` | `a6`, `4p` | A4→A6 4 ページ。切り込み不要 |
| `orihon4-right` | `4p-right` | 同 4 ページの右綴じ |
| `accordion8` | `jabara8` | 蛇腹（経本）折り 8 コマ。上下 2 本に切って貼り合わせる |
| `accordion4` | `jabara4` | 蛇腹折り 4 コマ。切り離し不要 |
| `nup8` | `8up` | 折らずに切り離すだけの A7 8 面付け（チラシ・カード向け） |
| `nup4` / `nup2` | `4up` / `2up` | 同 A6 4 面 / A5 2 面 |

同じ A7 チラシを 8 枚刷りたいときは:

```
orihon impose チラシ.pdf --layout nup8 --fill repeat -o 8面付け.pdf
```

---

## コマンドライン

インストール後は `src` フォルダで `python -m orihon …`、
`pip install .` していれば `orihon …` で使えます。

```bash
# PDF を折本に面付けする
orihon impose 原稿.pdf -o 折本.pdf

# レイアウトや用紙を指定する
orihon impose 原稿.pdf --layout orihon8-right --paper B5 --guides full

# 面付けしてそのままプリンタへ
orihon impose 原稿.pdf --print-to "EPSON PX-S5010"

# スプールを監視しつづける（常駐プロセスの実体）
orihon watch

# 設定画面
orihon gui

# レイアウト一覧（面付け図つき）
orihon layouts -v

# プリンタと印刷バックエンドの一覧
orihon printers

# 番号入りのテスト原稿を作って面付けを確かめる
orihon selftest --open

# 設定の表示・変更
orihon config
orihon config --set layout=orihon8-right --set output_mode=print

# 環境チェック
orihon doctor
```

Windows 以外（macOS / Linux）でも、仮想プリンタ以外の機能
（`impose` / `layouts` / `selftest` など）はそのまま動きます。

---

## 実プリンタへ自動で送る

`output_mode` を `print` にすると、面付けした PDF をそのままプリンタへ流します。
PDF を無人で印刷する標準 API が Windows に無いため、使えるものを順に試します。

1. **SumatraPDF** … `winget install SumatraPDF.SumatraPDF`（いちばん素直で速い）
2. **Ghostscript** … `winget install ArtifexSoftware.GhostScript`
3. **PDFtoPrinter**
4. 既定の PDF ビューアの `printto` 動詞
5. どれも無ければ PDF を開くだけ（手で印刷してください）

いま何が使えるかは `orihon printers` で確認できます。

> **印刷設定の注意**：折り位置がずれないよう、実プリンタ側では
> **「実際のサイズ」「100%」「拡大縮小なし」** で印刷してください。
> 「用紙に合わせる」だと少しだけ縮小されて、折り目と紙の端が合わなくなります。

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| 印刷しても何も起きない | `orihon doctor` を実行。監視プロセスが動いていない場合は `C:\ProgramData\OrihonPrinter\監視を開始.cmd` を実行するか、タスクスケジューラで **OrihonPrinter Watcher** を有効にしてください |
| 2 回目の印刷が失敗する | スプールに `job.pdf` が残っていると Print to PDF が書けません。監視プロセスを起動してから印刷し直してください |
| 保存ダイアログが出てしまう | プリンタのポートが `PORTPROMPT:` になっています。インストーラを再実行するとポートを付け直します |
| 文字が小さすぎる | 仮想プリンタのプロパティで用紙を **A7** にしてから印刷してください（A4 で刷ると 1/2.83 に縮みます） |
| 端が切れる | `safe_margin_mm` を大きく（5〜8mm）してください |
| 折り目と紙の端が合わない | 実プリンタ側で「拡大縮小なし・100%」にしてください |
| ログを見たい | `C:\ProgramData\OrihonPrinter\logs\orihon.log` |

---

## 開発

```bash
pip install -e ".[dev]"
pytest                          # 69 件のテスト
python tools/make_diagrams.py   # docs/images/*.svg を再生成
```

レイアウトを足したいときは `src/orihon/layouts.py` に 1 つ表を書くだけです。
`Layout.validate()` が「その面付けが本当に折本として成立するか」を
機械的に検査し、`fold_edges()` / `cut_edges()` が折り線と切り込みを
自動的に導き出します。物理的に折れない表は登録できません。

```
src/orihon/
  layouts.py   面付けレイアウトの定義・検証・折り線/切り込みの導出
  paper.py     用紙サイズと mm↔pt 変換
  impose.py    PyMuPDF による面付けエンジン
  config.py    設定の読み書き
  job.py       1 ジョブ分の処理（面付け → 出力）
  watcher.py   スプールフォルダの監視
  winprint.py  Windows のプリンタ一覧・PDF 送出
  gui.py       設定画面（tkinter）
  cli.py       コマンドライン
installer/     仮想プリンタのインストーラ（PowerShell）
docs/          面付けの解説と図
```

---

## ライセンス

MIT License（[LICENSE](LICENSE)）

面付けの仕様は
[キンコーズ・ジャパンのコラム「手軽に作れる『折本』ってどんなもの？」](https://www.kinkos.co.jp/column/folding-book/)
の図6 を参考にしています。図版そのものは同梱せず、
レイアウト定義から生成した図を `docs/images/` に置いています。
