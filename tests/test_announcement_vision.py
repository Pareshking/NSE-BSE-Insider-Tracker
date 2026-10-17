import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import announcement_vision as v  # noqa: E402
import announcement_reader as r  # noqa: E402


def f(shown=True):
    return {'shown': shown}


def test_needs_vision_and_better():
    safe = {'ok': True, 'headline': {'shown': True}, 'fields': [f(), f()], 'metrics': []}
    assert v.needs_vision(safe) is None
    held_head = {'ok': True, 'headline': {'shown': False}, 'fields': [f(False)], 'metrics': []}
    assert 'headline was held' in v.needs_vision(held_head)
    two_held = {'ok': True, 'headline': {'shown': True}, 'fields': [f(False), f(False)], 'metrics': []}
    assert 'values held' in v.needs_vision(two_held)
    assert v.needs_vision({'ok': False}) is None
    good = {'ok': True, 'headline': {'shown': True, 'text': 'h'}, 'fields': [f(), f()], 'metrics': []}
    assert v.better(good, held_head)
    worse = {'ok': True, 'headline': {'shown': True}, 'fields': [], 'metrics': []}
    assert not v.better(worse, safe)         # fewer shown values than the text card: keep the text card
    assert not v.better({'ok': True, 'headline': {'shown': False}, 'fields': [f()], 'metrics': []}, held_head)
    assert v.better(good, safe)              # a tie goes to the page image
    table_text = {**safe, 'category': 'esop', 'fields': [f()]}
    generic = {'ok': True, 'headline': {'shown': True, 'text': 'allots shares'}, 'fields': [], 'metrics': [], 'points': [{'text': 'x'}]}
    assert v.better(generic, table_text) and not v.better(generic, {**table_text, 'category': 'order_win'})
    assert v.shown_count({'fields': [{'name': 'entity', 'shown': True}, {'name': 'shares', 'shown': True}], 'metrics': []}) == 1
    assert v.needs_vision({**safe, 'category': 'esop'}) and 'table card' in v.needs_vision({**safe, 'category': 'esop'})
    assert v.needs_vision({**safe, 'category': 'order_win'}) is None


def test_triage_sends_figure_pages_and_names_the_rest():
    table = '\n'.join(f'Revenue from operations {i} 1,234.56 2,345.67 3,456.78 Rs crore profit' for i in range(8))
    sign = 'Yours faithfully\nCompany Secretary\nRegistered Office: Mumbai\nWebsite: x.com\n' + 'x ' * 60
    prose = 'The board met and discussed several matters of routine governance at some length today. ' * 3
    pick, why = v.triage(['Subject: Outcome of board meeting. ' * 4, table, sign, prose, ''])
    assert pick == [1, 2, 5]                    # first page, the figures, and the empty page (a scan)
    assert 'signature' in why[3] and 'left out' in why[4]


def test_triage_page_limit_is_named():
    table = '\n'.join(f'Revenue {i} 1,234.56 2,345.67 3,456.78 Rs crore profit' for i in range(8))
    pick, why = v.triage(['first page text ' * 10] + [table] * 5, max_pages=3)
    assert len(pick) == 3 and sum('over the page limit' in x for x in why.values()) == 3


def test_vision_text_uses_first_model_that_answers(monkeypatch):
    monkeypatch.setattr(v, 'pages_of', lambda d: ['first page text ' * 10])
    monkeypatch.setattr(v, 'render', lambda d, p: {1: b'png'})
    monkeypatch.setenv('READER_VISION_MODELS', 'gemini:a,gemini:b')
    tried = []

    def ask(model, prompt, imgs):
        tried.append(model)
        if model == 'a':
            raise RuntimeError('a: HTTP 429')
        return '{"ok": 1}', {'images': len(imgs)}

    got = v.vision_text(lambda note: 'PROMPT ' + note, b'%PDF', ask=ask)
    assert tried == ['a', 'b'] and got[0] == '{"ok": 1}' and got[1] == 'b' and 'attached as images' in got[4]
    monkeypatch.setattr(v, 'render', lambda d, p: {})
    assert v.vision_text(lambda n: n, b'%PDF', ask=ask) is None


def test_vision_repair_is_off_unless_enabled_and_keeps_text_when_not_better(monkeypatch):
    held = {'ok': True, 'headline': {'shown': False}, 'fields': [], 'metrics': []}
    row = {'symbol': 'X', 'exchange': 'NSE', 'subject': 's'}
    monkeypatch.delenv('READER_VISION', raising=False)
    assert r.vision_repair(row, 'doc', b'%PDF', held) is held
    monkeypatch.setenv('READER_VISION', '1')
    monkeypatch.setenv('GEMINI_API_KEY', 'k')
    monkeypatch.setattr(v, 'vision_text', lambda *a, **k: None)
    assert r.vision_repair(row, 'doc', b'%PDF', held) is held
    assert r.vision_repair(row, 'doc', None, held) is held


def test_vision_repair_fetches_the_pdf_when_the_text_came_from_cache(monkeypatch):
    held = {'ok': True, 'headline': {'shown': False}, 'fields': [], 'metrics': []}
    row = {'symbol': 'X', 'exchange': 'NSE', 'subject': 's', 'file_url': 'http://x/f.pdf'}
    monkeypatch.setenv('READER_VISION', '1')
    monkeypatch.setenv('GEMINI_API_KEY', 'k')
    seen = []
    monkeypatch.setattr(v, 'vision_text', lambda prompt_for, data, **k: seen.append(data) or None)
    assert r.vision_repair(row, 'doc', None, held, fetch=lambda url: b'%PDF-1.4 x') is held
    assert seen == [b'%PDF-1.4 x']
    assert r.vision_repair(row, 'doc', None, held, fetch=lambda url: b'PK zip') is held and len(seen) == 1


def test_two_readers_must_agree_on_the_headline_figures():
    text = {'headline': {'text': 'Federal Bank allots 7,100 equity shares', 'subtitle': {'text': 'under ESOS 2010 on 16 October 2026'}}}
    vision = {'headline': {'text': 'Federal Bank allots shares under stock option schemes'},
              'points': [{'text': 'allotted 90,869 equity shares under ESOS 2017'}, {'text': 'allotted 1,985 equity shares under ESIS 2023'}],
              'fields': [], 'metrics': []}
    assert v.unsupported_numbers(text, vision) == [7100.0]
    vision['points'].append({'text': 'allotted 7,100 equity shares under ESOS 2010'})
    assert v.unsupported_numbers(text, vision) == []
    assert v.numbers_of('on 16 October 2026, 31 days, Rs 73.85 Cr, 2,026 shares') == {73.85, 2026.0}
    # rounding is not a disagreement
    assert v.unsupported_numbers({'headline': {'text': 'GST notice of Rs 73.9 Cr'}}, {'headline': {'text': 'Rs 73.85 Cr'}}) == []
