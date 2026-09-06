/**
 * 折本のシートを撮った 1 枚の画像を、元のページ順の PDF に戻す。
 *
 * GAS には PDF を切り貼りする手段が無いので、Google スライドを
 * レンダラとして使う。1 スライド＝復元後の 1 ページとし、
 * シートの画像を「そのページのマスだけが見えるように」切り抜いて敷き、
 * 最後にプレゼンテーション全体を PDF に書き出す。
 */

/** ミリをポイント（1/72 インチ）に直す。 */
function mmToPt(value) {
  return value * 72.0 / 25.4;
}

/**
 * シートを回して見たときの (row, col) が、元の紙のどの位置に当たるか。
 * Python 版 unimpose._panel_clip と同じ対応。
 */
function sourceCell(layout, row, col, rotation) {
  const turn = ((rotation % 360) + 360) % 360;
  if (turn === 90) {
    return { row: layout.cols - 1 - col, col: row };
  }
  if (turn === 270) {
    return { row: col, col: layout.rows - 1 - row };
  }
  if (turn === 180) {
    return { row: layout.rows - 1 - row, col: layout.cols - 1 - col };
  }
  return { row: row, col: col };
}

/**
 * 復元後 1 ページの大きさ（ポイント）。
 *
 * A 判の紙を格子に割った 1 コマは、やはり A 判に近い比になる
 * （A4 横を 4 列 2 段なら A7 縦）。そこで、用紙を縦置き・横置きした
 * それぞれのパネルの比を出し、用紙そのものの比に近い方を採る。
 * 2 列 2 段のように差がつかない場合は、レイアウトが想定する持ち方
 * （turn=90 なら横長のパネル）で決める。
 */
function panelSizePt(layout, paperName) {
  const mmSize = orihonPaper(paperName);
  const ideal = Math.abs(Math.log(mmSize[0] / mmSize[1]));
  const candidates = [
    { w: mmSize[0], h: mmSize[1] },   // 縦置き
    { w: mmSize[1], h: mmSize[0] }    // 横置き
  ];
  const wantsLandscape = layout.turn === 90;

  let best = null;
  for (const sheet of candidates) {
    const panelW = sheet.w / layout.cols;
    const panelH = sheet.h / layout.rows;
    let score = Math.abs(Math.abs(Math.log(panelW / panelH)) - ideal);
    if ((panelW > panelH) === wantsLandscape) {
      score -= 1e-6;   // 差がつかないときの決め手
    }
    if (best === null || score < best.score) {
      best = { score: score, w: panelW, h: panelH };
    }
  }
  return { width: mmToPt(best.w), height: mmToPt(best.h) };
}

/**
 * シートの画像から、元のページ順のプレゼンテーションを組み立てる。
 * @return {string} 作ったプレゼンテーションの ID
 */
function buildPresentation(imageBlob, title, options) {
  const layout = orihonLayout(options.layout);
  const size = panelSizePt(layout, options.paper);
  const sheetRotate = ((options.sheetRotate % 360) + 360) % 360;
  const pageRotate = ((options.pageRotate % 360) + 360) % 360;

  // ページの大きさを指定して作る。指定が通らない環境でも動くよう、
  // 実際にできた大きさを読み直してから配置する。
  const created = Slides.Presentations.create({
    title: title,
    pageSize: {
      width: { magnitude: size.width, unit: 'PT' },
      height: { magnitude: size.height, unit: 'PT' }
    }
  });
  const presentationId = created.presentationId;

  const presentation = SlidesApp.openById(presentationId);
  const pageWidth = presentation.getPageWidth();
  const pageHeight = presentation.getPageHeight();
  if (Math.abs(pageWidth - size.width) > 1 || Math.abs(pageHeight - size.height) > 1) {
    console.warn(
      'ページの大きさを指定どおりにできませんでした（' +
      pageWidth.toFixed(1) + 'x' + pageHeight.toFixed(1) + 'pt）。' +
      '中身は正しく切り出されますが、用紙の比は変わります。'
    );
  }

  // 最初から入っているタイトルスライドは使わない
  const initial = presentation.getSlides();
  const cropRequests = [];

  for (let pageNo = 1; pageNo <= layout.cols * layout.rows; pageNo++) {
    const position = findPage(layout, pageNo);
    const cell = sourceCell(layout, position.row, position.col, sheetRotate);

    // 回して読む場合、格子の行と列も入れ替わる
    const gridCols = (sheetRotate % 180 === 0) ? layout.cols : layout.rows;
    const gridRows = (sheetRotate % 180 === 0) ? layout.rows : layout.cols;

    const slide = presentation.appendSlide(SlidesApp.PredefinedLayout.BLANK);
    const image = slide.insertImage(imageBlob);
    image.setLeft(0).setTop(0).setWidth(pageWidth).setHeight(pageHeight);

    // 面付けでかけた回転を打ち消し、シートの向きの分も戻す
    const angle = ((-layout.rotations[position.row][position.col]
                    - sheetRotate + pageRotate) % 360 + 360) % 360;
    if (angle !== 0) {
      image.setRotation(angle);
    }

    cropRequests.push({
      updateImageProperties: {
        objectId: image.getObjectId(),
        fields: 'cropProperties',
        imageProperties: {
          cropProperties: {
            leftOffset: cell.col / gridCols,
            rightOffset: 1 - (cell.col + 1) / gridCols,
            topOffset: cell.row / gridRows,
            bottomOffset: 1 - (cell.row + 1) / gridRows
          }
        }
      }
    });
  }

  for (const slide of initial) {
    slide.remove();
  }
  presentation.saveAndClose();

  // 切り抜きは SlidesApp からは指定できないので、Slides API でまとめて行う
  Slides.Presentations.batchUpdate({ requests: cropRequests }, presentationId);
  return presentationId;
}

/** レイアウトの中で、そのページ番号がどのマスにあるかを返す。 */
function findPage(layout, pageNo) {
  for (let row = 0; row < layout.rows; row++) {
    for (let col = 0; col < layout.cols; col++) {
      if (layout.pages[row][col] === pageNo) {
        return { row: row, col: col };
      }
    }
  }
  throw new Error('ページ ' + pageNo + ' がレイアウト ' + layout.name + ' にありません');
}

/**
 * シートの画像 1 枚を、元のページ順の PDF（Blob）に戻す。
 * 作業用のプレゼンテーションは最後に捨てる。
 */
function unimposeImage(imageBlob, baseName, options) {
  const presentationId = buildPresentation(
    imageBlob, '[作業用] ' + baseName, options
  );
  try {
    const pdf = DriveApp.getFileById(presentationId).getAs(MimeType.PDF);
    pdf.setName(options.outputName.replace('{name}', baseName));
    return pdf;
  } finally {
    // ドライブに作業用ファイルを残さない
    try {
      DriveApp.getFileById(presentationId).setTrashed(true);
    } catch (error) {
      console.warn('作業用ファイルを消せませんでした: ' + error);
    }
  }
}
