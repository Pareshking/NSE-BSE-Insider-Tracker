import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import announcement_sample as s  # noqa: E402


def pdf(*pages):
    d = pymupdf.open()
    for t in pages:
        pg = d.new_page()
        if t:
            pg.insert_text((72, 72), t)
    return d.tobytes()


LONG = 'Disclosure under Regulation 29(2) of SEBI takeover regulations by the promoter group of the company regarding release of pledge on shares ' * 2


def test_text_page_is_kept_and_a_blank_page_is_ocrd(monkeypatch):
    monkeypatch.setattr(s, 'ocr_page', lambda data, page, dpi=200: 'Pledge of 1,87,500 shares created in favour of 360 One ' * 3)
    text = s.pdf_text(pdf(LONG, ''))
    assert 'Regulation 29(2)' in text and 'Pledge of 1,87,500 shares' in text
    assert s.ocr_last()[:2] == [[2], []]


def test_ocr_that_gives_nothing_is_named_and_the_filing_is_not_read_in_part(monkeypatch):
    monkeypatch.setattr(s, 'ocr_page', lambda data, page, dpi=200: '')
    text, notes = s.text_of(pdf(LONG, ''))
    assert any(n.startswith('pages without text: 2') for n in notes) and 'Regulation 29(2)' in text


def test_a_page_with_text_is_never_ocrd(monkeypatch):
    called = []
    monkeypatch.setattr(s, 'ocr_page', lambda *a, **k: called.append(1) or '')
    s.pdf_text(pdf(LONG, LONG))
    assert not called and s.ocr_last()[:2] == [[], []]


def test_garbled_text_layer_needs_ocr():
    garbled = ' '.join(f'2J{i}9,51o 5A23st' for i in range(40))
    assert s._page_needs_ocr(garbled) and not s._page_needs_ocr(LONG)


def test_one_graphic_page_among_text_pages_does_not_drop_the_filing(monkeypatch):
    monkeypatch.setattr(s, 'ocr_page', lambda data, page, dpi=200: '')
    text, notes = s.text_of(pdf(*([LONG] * 5 + [''] + [LONG] * 4)))
    assert any(n.startswith('graphic pages without text: 6') for n in notes) and not any(n.startswith('pages without text') for n in notes)


def test_docling_is_used_only_when_it_reads_clearly_more_figures(monkeypatch):
    ocr = 'Total income 343.04 385.90 289.40 ni7o[ aato] G96'
    doc = '| Total income | 343.04 | 385.90 | 289.40 | 728.94 | 612.41 | 1,275.35 |\n| Profit | 71.70 | 44.16 | (3.96) | 115.86 | 22.37 | 88.54 |'
    assert s.better_table_text(ocr, doc) == doc
    assert s.better_table_text(doc, ocr) == doc            # tesseract's page was already the fuller one
    assert s.better_table_text('a 1.50 2.50', 'a 1.50 2.50 3.50') == 'a 1.50 2.50'   # one figure more is not clearly more


def test_docling_page_is_not_called_unless_enabled(monkeypatch):
    called = []
    monkeypatch.setattr(s, 'ocr_page', lambda *a, **k: 'Total income 343.04 385.90 289.40 728.94 612.41 1,275.35 71.70 44.16 (3.96) 115.86 ' * 2)
    monkeypatch.setattr(s, 'docling_page', lambda *a, **k: called.append(1) or '')
    monkeypatch.delenv('READER_DOCLING', raising=False)
    s.pdf_text(pdf(LONG, ''))
    assert not called
    monkeypatch.setenv('READER_DOCLING', '1')
    s.pdf_text(pdf(LONG, ''))
    assert called


def test_best_of_several_readers_wins_only_when_clearly_fuller():
    ocr = 'Total income 343.04 385.90 ni7o[ aato] G96'
    docling = '| Total income | 343.04 | 385.90 | 289.40 |'
    paddle = 'Total income 343.04 385.90 289.40 728.94 612.41 1,275.35 (3.96) 115.86'
    assert s.better_table_text(ocr, docling, paddle) == paddle
    assert s.better_table_text(paddle, ocr, docling) == paddle
    assert s.better_table_text(ocr) == ocr


def test_a_prose_page_goes_to_the_reader_whose_words_the_others_share():
    tess = 'Regislered Ofiice ldeal Centre Kolkata disclosure under Regulation 30 acquisition of equity shares of a listed entity'
    paddle = 'Registered Office Ideal Centre Kolkata disclosure under Regulation 30 acquisition of equity shares of a listed entity'
    docling = 'Registered Office Ideal Centre Kolkata disclosure under Regulation acquisition of equity shares of a listed entity'
    assert s.best_page_text(tess, paddle, docling) == paddle
    assert s.best_page_text(paddle, tess, docling) == paddle      # tesseract's own page stays unless another is clearly better
