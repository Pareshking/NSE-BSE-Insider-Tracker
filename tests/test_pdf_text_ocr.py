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
    assert s.ocr_last() == [[2], []]


def test_ocr_that_gives_nothing_is_named_and_the_filing_is_not_read_in_part(monkeypatch):
    monkeypatch.setattr(s, 'ocr_page', lambda data, page, dpi=200: '')
    text, notes = s.text_of(pdf(LONG, ''))
    assert any(n.startswith('pages without text: 2') for n in notes) and 'Regulation 29(2)' in text


def test_a_page_with_text_is_never_ocrd(monkeypatch):
    called = []
    monkeypatch.setattr(s, 'ocr_page', lambda *a, **k: called.append(1) or '')
    s.pdf_text(pdf(LONG, LONG))
    assert not called and s.ocr_last() == [[], []]


def test_garbled_text_layer_needs_ocr():
    garbled = ' '.join(f'2J{i}9,51o 5A23st' for i in range(40))
    assert s._page_needs_ocr(garbled) and not s._page_needs_ocr(LONG)
