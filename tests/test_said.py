from __future__ import annotations

import json
import sys
from pathlib import Path

from insiders_clean import said

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
from screens import filings_read as fr  # noqa: E402

DOC = {'isin': 'INE467B01029', 'calls': [
    {'event_id': 'nse:1', 'filed': '2026-07-15', 'call_date': '2026-07-15', 'source_url': 'https://x/q1.pdf', 'facts': [
        {'topic': 'margins', 'statement': 'We want to exit at 25% plus.', 'speaker': 'S', 'quote': 'We want to exit at 25% plus and strive to achieve it sooner'},
        {'topic': 'demand', 'statement': 'Manufacturing will turn around in Q2.', 'speaker': 'K', 'quote': 'manufacturing, we believe will turnaround in Q2'},
        {'topic': 'people', 'statement': 'Workforce was 593,798.', 'speaker': None, 'quote': 'Our workforce at the end of quarter stood at 593,798.'},
        {'topic': 'guidance', 'statement': 'We do not provide guidance.', 'speaker': None, 'quote': "We don't provide any specific revenue or earnings guidance"}]},
    {'event_id': 'nse:2', 'filed': '2026-10-14', 'call_date': '2026-10-14', 'source_url': 'https://x/q2.pdf', 'facts': [
        {'topic': 'margins', 'statement': 'Q2 margin will rise.', 'speaker': None, 'quote': 'we expect margin to rise'}]}]}


def test_only_calls_before_the_filing_are_used():
    items = said.pick(DOC, '2026-10-08', 3, [])
    assert items and all(i['call_date'] == '2026-07-15' for i in items)
    assert said.pick(DOC, '2026-07-01', 3, []) == []


def test_margin_statement_is_paired_with_the_operating_margin_figure():
    metrics = [{'label': 'Net Margin', 'value': '19.0'}, {'label': 'Operating Margin', 'value': '24.0'}]
    items = said.pick(DOC, '2026-10-08', 3, metrics)
    assert items[0]['metric']['label'] == 'Operating Margin'      # paired first
    assert 'exit at 25%' in items[0]['quote']
    assert any(i['metric'] is None for i in items[1:])


def test_a_statement_with_nothing_to_pair_is_kept_but_not_judged():
    items = said.pick(DOC, '2026-10-08', 3, [])
    assert all(i['metric'] is None for i in items)
    assert not any('beat' in str(i).lower() or 'missed' in str(i).lower() for i in items)


def test_card_block_shows_words_date_link_and_figure():
    r = {'category': 'financial_results', 'broadcast_at': '2026-10-08T10:00:00Z',
         'metrics': json.dumps([{'shown': True, 'label': 'Operating Margin', 'period': 'Q2 FY27', 'value': '24.0', 'unit': 'percent', 'number': 24.0}])}
    html = fr.said_html(r, DOC)
    assert 'Management said on the last call' in html and 'exit at 25% plus' in html and 'transcript' in html
    assert 'This quarter' in html and '24' in html
    assert fr.said_html({**r, 'category': 'order_win'}, DOC) == '' and fr.said_html(r, {}) == ''
