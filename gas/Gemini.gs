/**
 * 復元したメモを Gemini に読ませて、書き起こしを取り出す。
 *
 * 「送る中身を組み立てる」「返ってきたものを読む」「表の行に直す」は
 * Google の API を使わない素の関数にしてある。おかげでこの部分は
 * Node でそのまま動かせて、テスト（tests/test_gas.py）で確かめている。
 * 通信そのものだけが callGemini に閉じている。
 */

const GEMINI_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/';

/** インラインで送れる大きさの上限（安全側に見た値、MB）。 */
const GEMINI_MAX_INLINE_MB = 15;

/** 書き起こしのお願い。読めないものを埋めさせないことを重視している。 */
const TRANSCRIPTION_PROMPT = [
  '添付は、A4 を折って作った手書きメモを 1 ページずつに戻した PDF です。',
  'ページの順番はすでに正しく並んでいます。',
  '',
  '各ページについて、書かれている内容をそのまま書き起こしてください。',
  '',
  '守ってほしいこと:',
  '- 書かれていないことを補わないでください。推測で埋めないこと。',
  '- 読めない文字は […] と書いてください。ページ全体が白紙なら text を空にしてください。',
  '- 箇条書きや矢印などの構造は、できるだけそのまま残してください。',
  '- title は、そのページの見出しらしきものがあればそれを。無ければ空で構いません。',
  '- todos には「やること」として書かれている項目だけを入れてください。',
  '- tags には、内容を表す短い語を 3 つまで入れてください（例: 買い物, 打合せ）。',
  '- confidence は、読み取りの確からしさを high / medium / low で入れてください。'
].join('\n');

/** 返してほしい形。これを指定しておくと解釈のぶれが減る。 */
const TRANSCRIPTION_SCHEMA = {
  type: 'OBJECT',
  properties: {
    pages: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          page: { type: 'INTEGER' },
          title: { type: 'STRING' },
          text: { type: 'STRING' },
          todos: { type: 'ARRAY', items: { type: 'STRING' } },
          tags: { type: 'ARRAY', items: { type: 'STRING' } },
          confidence: { type: 'STRING' }
        },
        required: ['page', 'text']
      }
    },
    summary: { type: 'STRING' }
  },
  required: ['pages']
};

/** スプレッドシートの見出し行。 */
const SHEET_HEADER = [
  '処理日時', '元ファイル', 'ページ', '見出し', '本文',
  'やること', 'タグ', '確からしさ', 'PDF'
];

// ----------------------------------------------------------------------
// 素の関数（Google の API を使わない＝テストできる部分）
// ----------------------------------------------------------------------

/** Gemini に送る中身を組み立てる。 */
function buildTranscriptionRequest(base64Data, mimeType, prompt) {
  return {
    contents: [{
      role: 'user',
      parts: [
        { text: prompt || TRANSCRIPTION_PROMPT },
        { inlineData: { mimeType: mimeType, data: base64Data } }
      ]
    }],
    generationConfig: {
      temperature: 0,
      responseMimeType: 'application/json',
      responseSchema: TRANSCRIPTION_SCHEMA
    }
  };
}

/**
 * 返ってきたものから、ページごとの書き起こしを取り出す。
 * 途中で形が違っても落とさず、分かるところまで返す。
 */
function parseTranscription(response) {
  if (!response || !response.candidates || !response.candidates.length) {
    const blocked = response && response.promptFeedback && response.promptFeedback.blockReason;
    throw new Error(blocked
      ? 'Gemini が応答を返しませんでした（' + blocked + '）'
      : 'Gemini の応答に candidates がありません');
  }

  const candidate = response.candidates[0];
  if (candidate.finishReason && candidate.finishReason !== 'STOP') {
    console.warn('Gemini の応答が途中で終わっています: ' + candidate.finishReason);
  }

  const parts = (candidate.content && candidate.content.parts) || [];
  const text = parts.map(function (p) { return p.text || ''; }).join('');
  if (!text.trim()) {
    throw new Error('Gemini の応答が空でした');
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error('Gemini の応答を JSON として読めませんでした: ' + text.slice(0, 200));
  }

  const pages = (parsed.pages || []).map(function (page) {
    return {
      page: Number(page.page) || 0,
      title: String(page.title || '').trim(),
      text: String(page.text || '').trim(),
      todos: Array.isArray(page.todos) ? page.todos.map(String) : [],
      tags: Array.isArray(page.tags) ? page.tags.map(String) : [],
      confidence: String(page.confidence || '').trim()
    };
  });
  pages.sort(function (a, b) { return a.page - b.page; });
  return { pages: pages, summary: String(parsed.summary || '').trim() };
}

/** 書き起こしをスプレッドシートの行に直す（1 ページ 1 行）。 */
function transcriptionToRows(transcription, meta) {
  const stamp = meta.timestamp || '';
  return transcription.pages.map(function (page) {
    return [
      stamp,
      meta.sourceName || '',
      page.page,
      page.title,
      page.text,
      page.todos.join('\n'),
      page.tags.join(', '),
      page.confidence,
      meta.pdfUrl || ''
    ];
  });
}

// ----------------------------------------------------------------------
// 通信
// ----------------------------------------------------------------------

/** API キーはスクリプトプロパティに置く（コードに書かないこと）。 */
function getGeminiApiKey() {
  return PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY') || '';
}

/**
 * API キーを保存する。エディタでこの関数を一度だけ実行してください。
 * 引数に直接書かず、実行後にこの行は消しておくのが安全です。
 */
function setGeminiApiKey(key) {
  const value = String(key || '').trim();
  if (!value) {
    throw new Error('キーが空です。setGeminiApiKey("AIza...") のように呼んでください。');
  }
  PropertiesService.getScriptProperties().setProperty('GEMINI_API_KEY', value);
  return 'API キーを保存しました（' + value.slice(0, 6) + '… / ' + value.length + ' 文字）';
}

/** Gemini を呼ぶ。混雑していたら少し待って数回だけやり直す。 */
function callGemini(requestBody, model, apiKey) {
  const url = GEMINI_ENDPOINT + encodeURIComponent(model) + ':generateContent';
  let lastError = '';

  for (let attempt = 0; attempt < 3; attempt++) {
    const response = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      // キーは URL ではなくヘッダで送る（ログや履歴に残さないため）
      headers: { 'x-goog-api-key': apiKey },
      payload: JSON.stringify(requestBody),
      muteHttpExceptions: true
    });

    const code = response.getResponseCode();
    const body = response.getContentText();
    if (code === 200) {
      return JSON.parse(body);
    }
    lastError = 'HTTP ' + code + ': ' + body.slice(0, 300);

    if (code === 429 || code >= 500) {
      const wait = 2000 * Math.pow(2, attempt);
      console.warn('Gemini が混んでいます。' + (wait / 1000) + ' 秒待って試します（' + lastError + '）');
      Utilities.sleep(wait);
      continue;
    }
    if (code === 400 && body.indexOf('API key') >= 0) {
      throw new Error('Gemini の API キーが正しくないようです。setGeminiApiKey で入れ直してください。');
    }
    break;
  }
  throw new Error('Gemini を呼べませんでした: ' + lastError);
}

/**
 * 復元した PDF を Gemini に読ませる。
 * @return {{pages: Array, summary: string}}
 */
function transcribePdf(pdfBlob, model) {
  const apiKey = getGeminiApiKey();
  if (!apiKey) {
    throw new Error('API キーが未設定です。setGeminiApiKey("AIza...") を一度実行してください。');
  }

  const bytes = pdfBlob.getBytes();
  const megabytes = bytes.length / (1024 * 1024);
  if (megabytes > GEMINI_MAX_INLINE_MB) {
    throw new Error(
      'PDF が大きすぎます（' + megabytes.toFixed(1) + 'MB）。' +
      'ScanSnap の読み取り解像度を下げてみてください。'
    );
  }

  const request = buildTranscriptionRequest(
    Utilities.base64Encode(bytes), 'application/pdf', TRANSCRIPTION_PROMPT
  );
  return parseTranscription(callGemini(request, model, apiKey));
}
