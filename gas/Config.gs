/**
 * 設定。ここだけ書き換えれば動きます。
 *
 * フォルダ ID は、Google ドライブでフォルダを開いたときの URL の末尾です。
 *   https://drive.google.com/drive/folders/★この部分★
 */
const CONFIG = {
  /** ScanSnap の保存先。ここに入った画像を処理します。 */
  INBOX_FOLDER_ID: 'ここに入力フォルダの ID を貼る',

  /** 復元した PDF の置き場。空にすると入力フォルダと同じ場所に作ります。 */
  OUTPUT_FOLDER_ID: '',

  /** 処理し終わった元ファイルの移動先。空なら入力フォルダに残します。 */
  DONE_FOLDER_ID: '',

  /** 面付けレイアウト。orihon layouts で一覧できるものと同じ名前。 */
  LAYOUT: 'orihon8',

  /** 刷った（折った）用紙。A4 / B5 / 210x297 のような直接指定も可。 */
  PAPER: 'A4',

  /**
   * スキャンした紙を何度回して読むか（0 / 90 / 180 / 270）。
   * 復元したページが上下逆なら 180 に、横倒しなら 90 か 270 にします。
   */
  SHEET_ROTATE: 0,

  /** 復元した全ページに追加でかける回転（0 / 90 / 180 / 270）。 */
  PAGE_ROTATE: 0,

  /** 1 回の実行で処理する最大ファイル数（実行時間の上限に当てないため）。 */
  MAX_FILES_PER_RUN: 5,

  /** 出力ファイル名。{name} は元のファイル名（拡張子なし）に置き換わります。 */
  OUTPUT_NAME: '{name}_元原稿.pdf'
};

/** 処理できる画像の種類。 */
const SUPPORTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/bmp'];
