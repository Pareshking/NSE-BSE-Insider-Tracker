from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import management_said as ms  # noqa: E402

HEAD = 'July 15, 2026 Sub: Transcript of the earnings conference call held on July 9, 2026 ' + 'x ' * 8000


def test_transcript_needs_a_call_subject_the_word_and_length():
    assert ms.is_transcript('Analysts/Institutional Investor Meet/Con. Call Updates', HEAD)
    assert not ms.is_transcript('Analysts/Institutional Investor Meet/Con. Call Updates', 'Transcript ' + 'x' * 100)     # a notice
    assert not ms.is_transcript('Press Release', HEAD)
    assert not ms.is_transcript('Analysts/Institutional Investor Meet/Con. Call Updates', 'Audio recording link ' + 'x' * 20000)


def test_call_date_is_the_day_the_filing_says_else_the_filing_date():
    assert ms.call_date(HEAD, '2026-07-15') == '2026-07-09'
    assert ms.call_date('no date here', '2026-07-15') == '2026-07-15'


def test_sections_cover_the_text_once():
    text = ('Sentence one is here. ' * 2000)
    parts = ms.sections(text)
    assert len(parts) > 2 and ''.join(parts) == text and all(len(p) <= ms.SECTION for p in parts)


def test_choose_keeps_forward_looking_first_and_each_statement_once():
    facts = [{'topic': 'people', 'statement': 'Workforce was 5.', 'quote': 'workforce was 5'},
             {'topic': 'margins', 'statement': 'We expect margin to rise.', 'quote': 'we expect margin to rise'},
             {'topic': 'margins', 'statement': 'We expect margin to rise.', 'quote': 'we expect margin to rise'}]
    out = ms.choose(facts)
    assert [f['statement'] for f in out] == ['We expect margin to rise.', 'Workforce was 5.']
