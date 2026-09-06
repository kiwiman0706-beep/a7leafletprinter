/**
 * 入力フォルダを見張って、折本のシートを撮った画像を
 * 元のページ順の PDF に戻す。
 *
 * 使いはじめ:
 *   1. Config.gs のフォルダ ID を埋める
 *   2. checkSetup() を実行して、設定と権限を確かめる
 *   3. installTrigger() を実行して、定期実行を登録する
 */

/** 何分おきに入力フォルダを見に行くか。 */
const TRIGGER_MINUTES = 10;

/** 実行時間の上限（GAS は 6 分で打ち切られるので、手前で止める）。 */
const TIME_BUDGET_MS = 4 * 60 * 1000;

/**
 * 定期実行の入り口。入力フォルダの未処理ファイルを順に片付ける。
 */
function processInbox() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    console.log('前回の実行がまだ動いているので、今回は見送ります');
    return;
  }
  try {
    const started = Date.now();
    const inbox = DriveApp.getFolderById(requireConfig('INBOX_FOLDER_ID'));
    const outbox = resolveFolder(CONFIG.OUTPUT_FOLDER_ID, inbox);
    const done = CONFIG.DONE_FOLDER_ID ? DriveApp.getFolderById(CONFIG.DONE_FOLDER_ID) : null;

    const options = currentOptions();
    let processed = 0;
    const files = inbox.getFiles();

    while (files.hasNext()) {
      if (processed >= CONFIG.MAX_FILES_PER_RUN) {
        console.log('今回の上限 ' + CONFIG.MAX_FILES_PER_RUN + ' 件に達しました。続きは次回に回します');
        break;
      }
      if (Date.now() - started > TIME_BUDGET_MS) {
        console.log('時間が足りなくなったので、続きは次回に回します');
        break;
      }

      const file = files.next();
      if (!isSupportedImage(file)) {
        continue;
      }
      try {
        handleFile(file, outbox, done, options);
        processed++;
      } catch (error) {
        console.error(file.getName() + ' を処理できませんでした: ' + error);
      }
    }
    console.log(processed + ' 件処理しました');
  } finally {
    lock.releaseLock();
  }
}

/** 1 ファイル分の処理。 */
function handleFile(file, outbox, done, options) {
  const baseName = file.getName().replace(/\.[^.]+$/, '');
  console.log('処理します: ' + file.getName());

  const pdf = unimposeImage(file.getBlob(), baseName, options);
  const created = outbox.createFile(pdf);
  console.log('  → ' + created.getName());

  if (done) {
    file.moveTo(done);
  }
}

/** 扱える画像かどうか。 */
function isSupportedImage(file) {
  const type = file.getMimeType();
  if (SUPPORTED_IMAGE_TYPES.indexOf(type) >= 0) {
    return true;
  }
  if (type === MimeType.PDF) {
    console.warn(
      file.getName() + ' は PDF なので飛ばします。' +
      'GAS には PDF を画像に変換する手段がありません。' +
      'ScanSnap の保存形式を JPEG にしてください。'
    );
  }
  return false;
}

/** いまの設定から、逆面付けの指定を組み立てる。 */
function currentOptions() {
  return {
    layout: CONFIG.LAYOUT,
    paper: CONFIG.PAPER,
    sheetRotate: CONFIG.SHEET_ROTATE || 0,
    pageRotate: CONFIG.PAGE_ROTATE || 0,
    outputName: CONFIG.OUTPUT_NAME || '{name}_元原稿.pdf'
  };
}

function requireConfig(key) {
  const value = CONFIG[key];
  if (!value || value.indexOf('ここに') === 0) {
    throw new Error(
      'Config.gs の ' + key + ' を設定してください。' +
      'フォルダを開いたときの URL の末尾が ID です。'
    );
  }
  return value;
}

function resolveFolder(id, fallback) {
  return id ? DriveApp.getFolderById(id) : fallback;
}

// ----------------------------------------------------------------------
// 手で実行するもの
// ----------------------------------------------------------------------

/**
 * 設定と権限を確かめる。まずこれを実行してください。
 */
function checkSetup() {
  const report = [];

  try {
    const inbox = DriveApp.getFolderById(requireConfig('INBOX_FOLDER_ID'));
    report.push('[OK] 入力フォルダ: ' + inbox.getName());
    let images = 0;
    const files = inbox.getFiles();
    while (files.hasNext()) {
      if (isSupportedImage(files.next())) { images++; }
    }
    report.push('[--] 未処理の画像: ' + images + ' 件');
  } catch (error) {
    report.push('[NG] 入力フォルダ: ' + error.message);
  }

  for (const key of ['OUTPUT_FOLDER_ID', 'DONE_FOLDER_ID']) {
    if (!CONFIG[key]) {
      report.push('[--] ' + key + ' は未設定（' +
                  (key === 'OUTPUT_FOLDER_ID' ? '入力フォルダに出力します' : '元ファイルは動かしません') + '）');
      continue;
    }
    try {
      report.push('[OK] ' + key + ': ' + DriveApp.getFolderById(CONFIG[key]).getName());
    } catch (error) {
      report.push('[NG] ' + key + ': ' + error.message);
    }
  }

  try {
    const layout = orihonLayout(CONFIG.LAYOUT);
    const size = panelSizePt(layout, CONFIG.PAPER);
    report.push('[OK] レイアウト: ' + layout.title +
                '（' + layout.cols + '列 x ' + layout.rows + '段、' +
                '復元後 1 ページ ' + (size.width / 72 * 25.4).toFixed(0) + 'x' +
                (size.height / 72 * 25.4).toFixed(0) + 'mm）');
  } catch (error) {
    report.push('[NG] レイアウト: ' + error.message);
  }

  try {
    Slides.Presentations; // 高度なサービスが有効か
    report.push('[OK] Slides API（高度なサービス）が使えます');
  } catch (error) {
    report.push('[NG] Slides API が有効になっていません。' +
                'エディタ左の「サービス」から Google Slides API を追加してください');
  }

  const triggers = ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'processInbox'; });
  report.push(triggers.length
    ? '[OK] 定期実行は登録済みです'
    : '[--] 定期実行は未登録です（installTrigger() を実行してください）');

  const text = report.join('\n');
  console.log(text);
  return text;
}

/** 入力フォルダの 1 件だけを試しに処理する（トリガーを入れる前の確認用）。 */
function runOnce() {
  const inbox = DriveApp.getFolderById(requireConfig('INBOX_FOLDER_ID'));
  const outbox = resolveFolder(CONFIG.OUTPUT_FOLDER_ID, inbox);
  const files = inbox.getFiles();
  while (files.hasNext()) {
    const file = files.next();
    if (isSupportedImage(file)) {
      handleFile(file, outbox, null, currentOptions());   // 元ファイルは動かさない
      return '処理しました: ' + file.getName();
    }
  }
  return '処理できる画像が入力フォルダにありません';
}

/** 定期実行を登録する。 */
function installTrigger() {
  removeTrigger();
  ScriptApp.newTrigger('processInbox')
    .timeBased()
    .everyMinutes(TRIGGER_MINUTES)
    .create();
  const message = TRIGGER_MINUTES + ' 分おきの定期実行を登録しました';
  console.log(message);
  return message;
}

/** 定期実行を解除する。 */
function removeTrigger() {
  let removed = 0;
  for (const trigger of ScriptApp.getProjectTriggers()) {
    if (trigger.getHandlerFunction() === 'processInbox') {
      ScriptApp.deleteTrigger(trigger);
      removed++;
    }
  }
  if (removed) {
    console.log(removed + ' 件の定期実行を解除しました');
  }
  return removed;
}
