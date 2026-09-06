"""面付けの逆変換（スキャンから元のページ順に戻す）の検証。"""

import pymupdf
import pytest

from orihon import impose, layouts, paper, unimpose
from orihon.paper import mm


def _page_numbers(path) -> list[str]:
    """各ページに書かれている数字を、ページ順に取り出す。"""
    out = []
    with pymupdf.open(path) as doc:
        for index in range(doc.page_count):
            digits = [
                span["text"].strip()
                for block in doc.load_page(index).get_text("dict")["blocks"]
                for line in block.get("lines", [])
                for span in line["spans"]
                if span["text"].strip().isdigit()
            ]
            out.append(digits[0] if digits else "?")
    return out


def _uprightness(path) -> list[bool]:
    """各ページの文字がすべて正立しているか。"""
    out = []
    with pymupdf.open(path) as doc:
        for index in range(doc.page_count):
            dirs = [
                tuple(round(v) for v in line["dir"])
                for block in doc.load_page(index).get_text("dict")["blocks"]
                for line in block.get("lines", [])
            ]
            out.append(all(d == (1, 0) for d in dirs) if dirs else False)
    return out


# ----------------------------------------------------------------------
# 往復（面付け → 逆面付け）
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("layout_name", "pages", "source_size"),
    [
        ("orihon8", 8, "A7"),
        ("orihon8-right", 8, "A7"),
        ("orihon4", 4, "A6"),
        # 横長パネルのレイアウトには横長の原稿を渡す（縦長を渡すと面付け側が
        # 自動回転し、戻したページも寝たままになる。それは逆変換としては正しい）
        ("orihon8-landscape", 8, "105x74"),
        ("orihon4-landscape", 4, "148x105"),
        ("nup8", 8, "A7"),
    ],
)
def test_round_trip_restores_the_original_order(layout_name, pages, source_size, tmp_path):
    """面付けしたものを戻すと、元のページ順・正立に復元されること。"""
    src = impose.write_test_pdf(tmp_path / "src.pdf", pages=pages, size=source_size)
    sheet = tmp_path / "sheet.pdf"
    imposed = impose.impose_pdf(
        src, sheet, impose.ImposeOptions(layout=layout_name, guides="none")
    )

    back = tmp_path / "back.pdf"
    result = unimpose.unimpose_pdf(
        sheet, back,
        unimpose.UnimposeOptions(layout=layout_name, paper=imposed.paper, crop="never"),
    )

    assert result.pages == pages
    assert _page_numbers(back) == [str(i) for i in range(1, pages + 1)]
    assert all(_uprightness(back))


def test_round_trip_handles_several_sheets(tmp_path):
    src = impose.write_test_pdf(tmp_path / "src.pdf", pages=16, size="A7")
    sheet = tmp_path / "sheet.pdf"
    impose.impose_pdf(src, sheet, impose.ImposeOptions(layout="orihon8", guides="none"))

    result = unimpose.unimpose_pdf(
        sheet, tmp_path / "back.pdf",
        unimpose.UnimposeOptions(layout="orihon8", crop="never"),
    )
    assert result.sheets == 2
    assert result.pages == 16
    # 2 枚目は 1〜8 が繰り返される（1 冊目・2 冊目の別の本）
    assert _page_numbers(tmp_path / "back.pdf")[:8] == [str(i) for i in range(1, 9)]


def test_max_sheets_limits_the_work(tmp_path):
    src = impose.write_test_pdf(tmp_path / "src.pdf", pages=16, size="A7")
    sheet = tmp_path / "sheet.pdf"
    impose.impose_pdf(src, sheet, impose.ImposeOptions(layout="orihon8", guides="none"))

    result = unimpose.unimpose_pdf(
        sheet, tmp_path / "back.pdf",
        unimpose.UnimposeOptions(layout="orihon8", crop="never", max_sheets=1),
    )
    assert result.sheets == 1 and result.pages == 8
    assert any("max_sheets" in w for w in result.warnings)


# ----------------------------------------------------------------------
# スキャンらしい入力
# ----------------------------------------------------------------------
@pytest.fixture()
def scanned(tmp_path):
    """余白付き・位置ずれ付きでラスタ化した、スキャンらしい PDF を作る。"""
    src = impose.write_test_pdf(tmp_path / "src.pdf", pages=8, size="A7")
    sheet = tmp_path / "sheet.pdf"
    impose.impose_pdf(src, sheet, impose.ImposeOptions(layout="orihon8", guides="cut"))

    with pymupdf.open(sheet) as doc:
        pix = doc.load_page(0).get_pixmap(dpi=150)
    width, height = pix.width * 72 / 150, pix.height * 72 / 150
    offset_x, offset_y = mm(9), mm(3)

    # フラットベッドの隅に置いたときのように、縦横で不均等な余白を付ける。
    # 余白が用紙と同じ比だと「既に用紙ちょうどに切られたもの」と区別できない
    scan = pymupdf.open()
    page = scan.new_page(width=width + mm(38), height=height + mm(6))
    page.draw_rect(page.rect, fill=(1, 1, 1), color=None)
    page.insert_image(
        pymupdf.Rect(offset_x, offset_y, offset_x + width, offset_y + height), pixmap=pix
    )
    path = tmp_path / "scan.pdf"
    scan.save(str(path))
    scan.close()
    return path, pymupdf.Rect(offset_x, offset_y, offset_x + width, offset_y + height)


def test_sheet_is_located_within_a_fraction_of_a_millimetre(scanned):
    """スキャナの余白と位置ずれがあっても、紙の位置をほぼ正確に当てること。"""
    path, truth = scanned
    layout = layouts.get("orihon8")
    with pymupdf.open(path) as doc:
        content, rotation, landscape, notes = unimpose.resolve_sheet(
            doc.load_page(0), layout, paper.get("A4"), unimpose.UnimposeOptions()
        )
    assert landscape is True          # orihon8 は A4 横で刷る
    assert rotation == 0
    assert notes == []
    for got, want in ((content.x0, truth.x0), (content.y0, truth.y0),
                      (content.x1, truth.x1), (content.y1, truth.y1)):
        assert abs(got - want) < mm(1.5), f"{got:.1f} != {want:.1f}"


def test_scanned_sheet_round_trips(scanned, tmp_path):
    path, _truth = scanned
    result = unimpose.unimpose_pdf(path, tmp_path / "back.pdf")
    assert result.pages == 8
    assert result.cropped is True
    assert result.warnings == []


def test_ink_detection_finds_nothing_on_a_blank_page(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=mm(210), height=mm(297))
    blank = tmp_path / "blank.pdf"
    doc.save(str(blank))
    doc.close()
    with pymupdf.open(blank) as d:
        assert unimpose.detect_content_rect(d.load_page(0)) is None


def test_blank_page_falls_back_to_the_whole_sheet(tmp_path):
    """白紙でも落ちないこと（crop=always で探しても見つからない場合）。"""
    doc = pymupdf.open()
    doc.new_page(width=mm(320), height=mm(210))     # A4 とは違う比にしておく
    blank = tmp_path / "blank.pdf"
    doc.save(str(blank))
    doc.close()

    result = unimpose.unimpose_pdf(
        blank, tmp_path / "back.pdf", unimpose.UnimposeOptions(crop="always")
    )
    assert result.pages == 8          # 白紙 8 ページになる
    assert any("見つけられず" in w for w in result.warnings)


def test_a_sheet_already_trimmed_to_the_paper_is_left_alone(tmp_path):
    """ScanSnap のように用紙ちょうどで取り込まれたものは、切り出さないこと。

    手書きのメモは紙の一部にしか書かれていないので、インクの範囲を紙と
    取り違えると全部ずれてしまう。用紙の比と合っていればそのまま使う。
    """
    doc = pymupdf.open()
    page = doc.new_page(width=mm(297), height=mm(210))     # A4 横ちょうど
    # 紙の真ん中あたりにだけ手書き風の線を引く
    for i in range(6):
        page.draw_line(pymupdf.Point(mm(90), mm(60 + i * 6)),
                       pymupdf.Point(mm(190), mm(62 + i * 6)),
                       color=(0.1, 0.1, 0.3), width=1.2)
    path = tmp_path / "memo.pdf"
    doc.save(str(path))
    doc.close()

    layout = layouts.get("orihon8")
    with pymupdf.open(path) as d:
        scanned_page = d.load_page(0)
        content, rotation, landscape, notes = unimpose.resolve_sheet(
            scanned_page, layout, paper.get("A4"), unimpose.UnimposeOptions()
        )
        assert content == scanned_page.rect     # 紙面まるごとを使う
    assert (rotation, landscape, notes) == (0, True, [])


def test_always_would_crop_the_same_memo(tmp_path):
    """crop=always にすると、同じメモでも文字の範囲を紙と誤認すること。

    「迷ったら切らない」を既定にしている理由を、動きで残しておく。
    """
    doc = pymupdf.open()
    page = doc.new_page(width=mm(297), height=mm(210))
    for i in range(6):
        page.draw_line(pymupdf.Point(mm(90), mm(60 + i * 6)),
                       pymupdf.Point(mm(190), mm(62 + i * 6)),
                       color=(0.1, 0.1, 0.3), width=1.2)
    path = tmp_path / "memo.pdf"
    doc.save(str(path))
    doc.close()

    with pymupdf.open(path) as d:
        content, _rot, _land, notes = unimpose.resolve_sheet(
            d.load_page(0), layouts.get("orihon8"), paper.get("A4"),
            unimpose.UnimposeOptions(crop="always"),
        )
        assert content != d.load_page(0).rect
    assert any("小さすぎます" in n for n in notes)


def test_images_can_be_used_as_input(scanned, tmp_path):
    """スキャナが PNG で出してきても読めること。"""
    path, _ = scanned
    with pymupdf.open(path) as doc:
        doc.load_page(0).get_pixmap(dpi=120).save(str(tmp_path / "scan.png"))

    result = unimpose.unimpose_pdf(tmp_path / "scan.png", tmp_path / "back.pdf")
    assert result.pages == 8


# ----------------------------------------------------------------------
# 向きと縦横比
# ----------------------------------------------------------------------
def test_rotation_is_detected_from_the_aspect_ratio():
    layout = layouts.get("orihon8")
    a4 = paper.get("A4")
    landscape = pymupdf.Rect(0, 0, mm(297), mm(210))
    portrait = pymupdf.Rect(0, 0, mm(210), mm(297))
    assert unimpose.choose_sheet_rotation(landscape, layout, a4) == 0
    assert unimpose.choose_sheet_rotation(portrait, layout, a4) == 90


def test_square_grids_default_to_no_rotation():
    """2 列 2 段のように、どちらに読んでもパネルの形が同じ場合は回さない。

    縦横比だけでは判断できないので、素直な向きを既定にしている。
    ずれていれば --sheet-rotate で直してもらう。
    """
    layout = layouts.get("orihon4")
    a4 = paper.get("A4")
    assert unimpose.choose_sheet_rotation(
        pymupdf.Rect(0, 0, mm(210), mm(297)), layout, a4) == 0
    assert unimpose.choose_sheet_rotation(
        pymupdf.Rect(0, 0, mm(297), mm(210)), layout, a4) == 0


def test_rotation_follows_the_layout(scanned):
    """横長パネルのレイアウトでは、期待する紙の向きも変わること。"""
    a4 = paper.get("A4")
    portrait = pymupdf.Rect(0, 0, mm(210), mm(297))
    assert unimpose.choose_sheet_rotation(
        portrait, layouts.get("orihon8-landscape"), a4) == 0


def test_sideways_scan_is_restored(tmp_path):
    """紙を 90 度倒して取り込んでも、元のページ順に戻せること。"""
    src = impose.write_test_pdf(tmp_path / "src.pdf", pages=8, size="A7")
    sheet = tmp_path / "sheet.pdf"
    impose.impose_pdf(src, sheet, impose.ImposeOptions(layout="orihon8", guides="none"))

    # シートを 90 度回した PDF を作る（横置きスキャンの再現）
    turned = pymupdf.open()
    with pymupdf.open(sheet) as doc:
        rect = doc.load_page(0).rect
        page = turned.new_page(width=rect.height, height=rect.width)
        page.show_pdf_page(page.rect, doc, 0, rotate=90)
    turned_path = tmp_path / "turned.pdf"
    turned.save(str(turned_path))
    turned.close()

    result = unimpose.unimpose_pdf(
        turned_path, tmp_path / "back.pdf",
        unimpose.UnimposeOptions(layout="orihon8", crop="never"),
    )
    assert result.sheet_rotate == 90
    assert _page_numbers(tmp_path / "back.pdf") == [str(i) for i in range(1, 9)]
    assert all(_uprightness(tmp_path / "back.pdf"))


def test_fit_to_aspect_only_grows():
    bounds = pymupdf.Rect(0, 0, 1000, 1000)
    square = pymupdf.Rect(300, 300, 600, 600)          # 1:1、広げる余地がある
    grown, clipped = unimpose.fit_to_aspect(square, 2.0, bounds)
    assert clipped is False
    assert grown.width == pytest.approx(600)           # 高さ 300 x 2.0
    assert grown.height == pytest.approx(300)          # 高さは変えない（狭めない）
    # 中心は動かさない
    assert (grown.x0 + grown.x1) / 2 == pytest.approx(450)
    assert (grown.y0 + grown.y1) / 2 == pytest.approx(450)


def test_fit_to_aspect_reports_when_it_runs_out_of_paper():
    bounds = pymupdf.Rect(0, 0, 400, 400)
    rect = pymupdf.Rect(10, 100, 390, 300)
    _grown, clipped = unimpose.fit_to_aspect(rect, 5.0, bounds)
    assert clipped is True


def test_fit_aspect_can_be_turned_off(scanned):
    """補正を切ったら、見つけたインクの範囲がそのまま使われること。"""
    path, _truth = scanned
    layout = layouts.get("orihon8")
    opts = unimpose.UnimposeOptions(crop="always", fit_aspect=False)
    with pymupdf.open(path) as doc:
        page = doc.load_page(0)
        raw, _rot, _landscape, _notes = unimpose.resolve_sheet(
            page, layout, paper.get("A4"), opts
        )
        ink = unimpose.detect_content_rect(page, opts.ink_threshold, opts.ink_ratio,
                                           min_ink_pixels=2)
    # 補正なしなので、比を用紙に合わせに行かない
    assert abs(raw.width - ink.width) < 1.0
    assert abs(raw.height - ink.height) < 1.0


def test_page_rotate_turns_every_output_page(tmp_path):
    src = impose.write_test_pdf(tmp_path / "src.pdf", pages=8, size="A7")
    sheet = tmp_path / "sheet.pdf"
    impose.impose_pdf(src, sheet, impose.ImposeOptions(layout="orihon8", guides="none"))

    result = unimpose.unimpose_pdf(
        sheet, tmp_path / "back.pdf",
        unimpose.UnimposeOptions(layout="orihon8", crop="never", page_rotate=90),
    )
    assert result.pages == 8
    with pymupdf.open(result.output) as doc:
        rect = doc.load_page(0).rect
    assert rect.width > rect.height      # 縦長パネルが横向きになる


# ----------------------------------------------------------------------
# 確認用のプレビュー
# ----------------------------------------------------------------------
def test_preview_marks_every_panel(scanned, tmp_path):
    path, _ = scanned
    out = unimpose.preview_pdf(path, tmp_path / "preview.pdf")
    assert out.is_file()
    with pymupdf.open(out) as doc:
        assert doc.page_count == 1
        text = doc.load_page(0).get_text()
    # 1〜8 の番号が重ねて描かれている
    for number in range(1, 9):
        assert str(number) in text


def test_preview_and_output_use_the_same_split(scanned, tmp_path):
    """プレビューで確かめた位置と、実際に切り出す位置が食い違わないこと。"""
    path, _ = scanned
    layout = layouts.get("orihon8")
    opts = unimpose.UnimposeOptions()
    with pymupdf.open(path) as doc:
        first = unimpose.resolve_sheet(doc.load_page(0), layout, paper.get("A4"), opts)
        second = unimpose.resolve_sheet(doc.load_page(0), layout, paper.get("A4"), opts)
    assert first[0] == second[0] and first[1] == second[1]


def test_empty_input_is_rejected():
    with pymupdf.open() as empty:
        with pytest.raises(ValueError, match="ページがありません"):
            unimpose.unimpose_document(empty)


def test_unknown_layout_raises(tmp_path):
    src = impose.write_test_pdf(tmp_path / "s.pdf", pages=8, size="A7")
    with pytest.raises(KeyError):
        unimpose.unimpose_pdf(src, tmp_path / "o.pdf",
                              unimpose.UnimposeOptions(layout="でたらめ"))
