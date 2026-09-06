/**
 * 折本のレイアウト定義。
 *
 * このファイルは自動生成です。直接編集しないでください。
 * 元は src/orihon/layouts.py で、次のコマンドで作り直せます:
 *
 *     python tools/make_gas_layouts.py
 *
 * pages    … 行優先（先頭が用紙の上段）で並べたページ番号
 * rotations… 同じ形の配列。そのマスの中身が何度回して刷られているか
 * turn     … 仕上がりを立てて読む(0) か、横に倒して上にめくる(90) か
 */
const ORIHON_DEFAULT_LAYOUT = "orihon8";

const ORIHON_LAYOUTS = [
  {
    name: "orihon8",
    title: "折本 8ページ（A4→A7・左綴じ）",
    kind: "foldbook",
    binding: "left",
    turn: 0,
    cols: 4,
    rows: 2,
    pages: [
      [7, 6, 5, 4],
      [8, 1, 2, 3]
    ],
    rotations: [
      [180, 180, 180, 180],
      [0, 0, 0, 0]
    ],
    aliases: ["a7", "8p", "orihon8-left"],
  },
  {
    name: "orihon8-right",
    title: "折本 8ページ（A4→A7・右綴じ）",
    kind: "foldbook",
    binding: "right",
    turn: 0,
    cols: 4,
    rows: 2,
    pages: [
      [4, 5, 6, 7],
      [3, 2, 1, 8]
    ],
    rotations: [
      [180, 180, 180, 180],
      [0, 0, 0, 0]
    ],
    aliases: ["8p-right", "a7-right"],
  },
  {
    name: "orihon4",
    title: "折本 4ページ（A4→A6・左綴じ）",
    kind: "foldbook",
    binding: "left",
    turn: 0,
    cols: 2,
    rows: 2,
    pages: [
      [3, 2],
      [4, 1]
    ],
    rotations: [
      [180, 180],
      [0, 0]
    ],
    aliases: ["a6", "4p"],
  },
  {
    name: "orihon4-right",
    title: "折本 4ページ（A4→A6・右綴じ）",
    kind: "foldbook",
    binding: "right",
    turn: 0,
    cols: 2,
    rows: 2,
    pages: [
      [2, 3],
      [1, 4]
    ],
    rotations: [
      [180, 180],
      [0, 0]
    ],
    aliases: ["4p-right", "a6-right"],
  },
  {
    name: "orihon8-landscape",
    title: "折本 8ページ（A4縦→A7横・天綴じ）",
    kind: "foldbook",
    binding: "top",
    turn: 90,
    cols: 2,
    rows: 4,
    pages: [
      [8, 7],
      [1, 6],
      [2, 5],
      [3, 4]
    ],
    rotations: [
      [0, 180],
      [0, 180],
      [0, 180],
      [0, 180]
    ],
    aliases: ["a7-yoko", "slide", "slide8", "8p-landscape"],
  },
  {
    name: "orihon8-landscape-bottom",
    title: "折本 8ページ（A4縦→A7横・地綴じ）",
    kind: "foldbook",
    binding: "bottom",
    turn: 90,
    cols: 2,
    rows: 4,
    pages: [
      [3, 4],
      [2, 5],
      [1, 6],
      [8, 7]
    ],
    rotations: [
      [0, 180],
      [0, 180],
      [0, 180],
      [0, 180]
    ],
    aliases: ["a7-yoko-rev", "slide8-rev"],
  },
  {
    name: "orihon4-landscape",
    title: "折本 4ページ（A4横→A6横・天綴じ）",
    kind: "foldbook",
    binding: "top",
    turn: 90,
    cols: 2,
    rows: 2,
    pages: [
      [4, 3],
      [1, 2]
    ],
    rotations: [
      [0, 180],
      [0, 180]
    ],
    aliases: ["a6-yoko", "slide4", "4p-landscape"],
  },
  {
    name: "accordion8",
    title: "蛇腹折り 8ページ（A4横・切り込みなし）",
    kind: "accordion",
    binding: "none",
    turn: 0,
    cols: 4,
    rows: 2,
    pages: [
      [1, 2, 3, 4],
      [5, 6, 7, 8]
    ],
    rotations: [
      [0, 0, 0, 0],
      [0, 0, 0, 0]
    ],
    aliases: ["jabara8"],
  },
  {
    name: "accordion4",
    title: "蛇腹折り 4ページ（A4横・切り込みなし）",
    kind: "accordion",
    binding: "none",
    turn: 0,
    cols: 4,
    rows: 1,
    pages: [
      [1, 2, 3, 4]
    ],
    rotations: [
      [0, 0, 0, 0]
    ],
    aliases: ["jabara4"],
  },
  {
    name: "nup8",
    title: "8面付け A7（折らずに切り離すだけ）",
    kind: "grid",
    binding: "none",
    turn: 0,
    cols: 4,
    rows: 2,
    pages: [
      [1, 2, 3, 4],
      [5, 6, 7, 8]
    ],
    rotations: [
      [0, 0, 0, 0],
      [0, 0, 0, 0]
    ],
    aliases: ["8up", "a7x8"],
  },
  {
    name: "nup4",
    title: "4面付け A6（折らずに切り離すだけ）",
    kind: "grid",
    binding: "none",
    turn: 0,
    cols: 2,
    rows: 2,
    pages: [
      [1, 2],
      [3, 4]
    ],
    rotations: [
      [0, 0],
      [0, 0]
    ],
    aliases: ["4up", "a6x4"],
  },
  {
    name: "nup2",
    title: "2面付け A5（折らずに切り離すだけ）",
    kind: "grid",
    binding: "none",
    turn: 0,
    cols: 2,
    rows: 1,
    pages: [
      [1, 2]
    ],
    rotations: [
      [0, 0]
    ],
    aliases: ["2up", "a5x2"],
  },
];

/** 用紙サイズ（ミリ、縦置きのときの寸法）。 */
const ORIHON_PAPERS = {
  "A3": [297.0, 420.0],
  "A4": [210.0, 297.0],
  "A5": [148.0, 210.0],
  "A6": [105.0, 148.0],
  "A7": [74.0, 105.0],
  "B4": [257.0, 364.0],
  "B5": [182.0, 257.0],
  "B6": [128.0, 182.0],
  "Letter": [215.9, 279.4],
  "Legal": [215.9, 355.6],
  "Tabloid": [279.4, 431.8],
};

/** 名前か別名からレイアウトを引く。 */
function orihonLayout(name) {
  const key = String(name || ORIHON_DEFAULT_LAYOUT).trim().toLowerCase();
  for (const layout of ORIHON_LAYOUTS) {
    if (layout.name === key || layout.aliases.indexOf(key) >= 0) {
      return layout;
    }
  }
  throw new Error(
    '未知のレイアウト "' + name + '" です。使えるのは: ' +
    ORIHON_LAYOUTS.map(function (l) { return l.name; }).join(', ')
  );
}

/** 用紙名から [幅mm, 高さmm]（縦置き）を引く。 */
function orihonPaper(name) {
  const key = String(name || 'A4').trim();
  for (const paperName of Object.keys(ORIHON_PAPERS)) {
    if (paperName.toLowerCase() === key.toLowerCase()) {
      return ORIHON_PAPERS[paperName];
    }
  }
  const match = key.match(/^(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)$/);
  if (match) {
    return [parseFloat(match[1]), parseFloat(match[2])];
  }
  throw new Error('未知の用紙 "' + name + '" です。');
}
