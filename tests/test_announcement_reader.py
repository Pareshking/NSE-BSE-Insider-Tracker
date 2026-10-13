"""The announcement reader (scripts/announcement_reader.py): checks on each value, read-once rules, lanes
falling back, and the reads written to an in-memory R2. No model or exchange is called."""
from __future__ import annotations

import io
import json
from datetime import date

import announcement_reader as ar
import pandas as pd
import pytest
from test_archive_and_writer import FakeR2

DOC = ('Allotment of 1,81,10,473 Equity Shares at the issue price of Rs. 165.65 per Equity Share to Qualified '
       'Institutional Buyers, aggregating to Rs. 299,99,99,852.45 (Rupees Two Hundred Ninety-Nine Crore). '
       'The Record Date is October 1, 2026. Hyundai plans an investment of USD 15.5 billion by 2030.')


def test_values_are_shown_only_when_their_quote_digits_and_unit_hold():
    out = {'category': 'qip', 'fields': [
        {'name': 'price_per_share', 'value': '165.65', 'quote': 'at the issue price of Rs. 165.65 per Equity Share'},
        {'name': 'shares', 'value': '1,81,10,473', 'quote': 'Allotment of 1,81,10,473 Equity Shares'},
        {'name': 'amount', 'value': '299,99,99,852.45', 'quote': 'aggregating to Rs. 299,99,99,852.45 (Rupees'},
        {'name': 'amount_unit', 'value': 'crore', 'quote': 'Rupees Two Hundred Ninety-Nine Crore'},
        {'name': 'record_date', 'value': 'October 1, 2026', 'quote': 'The Record Date is October 1, 2026'},
        {'name': 'entity', 'value': 'listed', 'quote': 'Allotment of 1,81,10,473 Equity Shares'},
        {'name': 'discount_pct', 'value': '5', 'quote': 'a discount of 5% to the floor price'}],
        'metrics': [{'label': 'investment', 'period': '2030', 'value': '15.5', 'unit': 'billion',
                     'quote': 'an investment of USD 15.5 billion by 2030'}]}
    cat, fields, metrics = ar.validate(out, DOC)
    f = {x['name']: x for x in fields}
    assert cat == 'qip'
    assert f['price_per_share']['shown'] and f['price_per_share']['number'] == 165.65
    assert f['shares']['shown'] and f['shares']['number'] == 18110473 and f['shares']['evidence'] == 'exact'
    assert not f['amount']['shown'] and 'unit not backed' in f['amount']['reason']   # crore only in the words
    assert f['record_date']['shown'] and f['record_date']['date'] == '2026-10-01'
    assert not f['entity']['shown'] and f['entity']['reason'] == 'entity labels not shown yet'
    assert not f['discount_pct']['shown'] and 'quote not found' in f['discount_pct']['reason']
    assert metrics[0]['shown'] and metrics[0]['number'] == 15.5e9
    _, fields, _ = ar.validate({'fields': [{'name': 'amount', 'value': '15.5',
                                            'quote': 'an investment of USD 15.5 billion by 2030'}]}, DOC)
    assert not fields[0]['shown']   # unit left out: 15.5 is not the amount
    assert ar.validate(None, DOC) == (None, [], [])


def test_second_reader_agreement_per_shown_field():
    main = [{'name': 'price_per_share', 'shown': True, 'number': 165.65},
            {'name': 'record_date', 'shown': True, 'date': '2026-10-01'},
            {'name': 'shares', 'shown': True, 'number': 100}, {'name': 'amount', 'shown': False, 'number': 1}]
    second = [{'name': 'price_per_share', 'number': 165.65}, {'name': 'record_date', 'date': '2026-10-02'}]
    assert ar.agreement(main, second) == {'price_per_share': True, 'record_date': False, 'shares': None}


def _cand(eid, exchange, isin, at, subject, detail='', group='fund_raise', mcap=5e10, **kw):
    return {'event_id': eid, 'exchange': exchange, 'market': 'equities', 'isin': isin, 'symbol': 'X', 'company': 'X Ltd',
            'subject': subject, 'detail': detail, 'group': group, 'file_url': f'https://f/{eid}.pdf', 'file_type': 'pdf',
            'broadcast_at': at, 'broadcast_date': at[:10], 'market_cap': mcap, **kw}


def test_choose_reads_once_skips_small_and_routine_and_retries_failures():
    today = date(2026, 10, 13)
    c = pd.DataFrame([
        _cand('nse:1', 'NSE', 'INE1', '2026-10-13T10:00:00+05:30', 'Preferential issue', 'Allotment of warrants to promoters'),
        _cand('bse:a', 'BSE', 'INE1', '2026-10-13T10:02:00+05:30', 'Preferential Issue', 'Allotment of warrants'),
        _cand('nse:2', 'NSE', 'INE2', '2026-10-13T11:00:00+05:30', 'Trading Window', group='routine'),
        _cand('nse:3', 'NSE', 'INE3', '2026-10-13T12:00:00+05:30', 'Buyback', mcap=5e8),
        _cand('nse:4', 'NSE', 'INE4', '2026-10-12T09:00:00+05:30', 'Rights Issue'),
        _cand('nse:5', 'NSE', 'INE5', '2026-10-10T09:00:00+05:30', 'Rights Issue'),   # older than yesterday
        _cand('nse:6', 'NSE', 'INE6', '2026-10-13T13:00:00+05:30', 'Buyback'),
        _cand('nse:7', 'NSE', 'INE7', '2026-10-13T14:00:00+05:30', 'Buyback')])
    done = pd.DataFrame([{**_cand('nse:6', 'NSE', 'INE6', '2026-10-13T13:00:00+05:30', 'Buyback'), 'status': 'read', 'tries': 1,
                          'prompt_version': ar.PROMPT_VERSION},
                         {**_cand('nse:7', 'NSE', 'INE7', '2026-10-13T14:00:00+05:30', 'Buyback'), 'status': 'failed', 'tries': 1}])
    to_read, status, counts = ar.choose(c, done, today)
    assert list(to_read['event_id']) == ['nse:7', 'nse:1', 'nse:4']   # today newest first, then yesterday
    assert to_read.set_index('event_id')['tries']['nse:7'] == 1          # a failure is tried again
    st = status.set_index('event_id')
    assert st.loc['bse:a', 'status'] == 'same_filing_other_exchange' and st.loc['bse:a', 'same_as'] == 'nse:1'
    assert st.loc['nse:3', 'status'] == 'below_100_cr'
    assert counts == {'candidates': 7, 'routine_or_no_file': 1, 'already_done': 1, 'below_100_cr': 1,
                      'same_filing_other_exchange': 1, 'to_read': 3}
    gave_up = done.assign(tries=ar.MAX_TRIES)
    assert 'nse:7' not in set(ar.choose(c, gave_up, today)[0]['event_id'])


def test_different_subjects_or_hours_apart_are_not_the_same_filing():
    a = _cand('nse:1', 'NSE', 'INE1', '2026-10-13T10:00:00+05:30', 'Outcome of Board Meeting', 'approved fund raising by QIP')
    assert ar.same_filing(a, _cand('bse:1', 'BSE', 'INE1', '2026-10-13T10:05:00+05:30', 'Outcome of Board Meeting', 'QIP fund raising approved'))
    assert not ar.same_filing(a, _cand('bse:2', 'BSE', 'INE1', '2026-10-13T10:05:00+05:30', 'Credit Rating', 'rating reaffirmed'))
    assert not ar.same_filing(a, _cand('bse:3', 'BSE', 'INE1', '2026-10-13T19:00:00+05:30', 'Outcome of Board Meeting', 'approved fund raising by QIP'))
    assert not ar.same_filing(a, {**a, 'event_id': 'nse:9'})   # same exchange: two filings


class FakeClient:
    def __init__(self, replies):
        self.replies, self.attempts, self.asked = list(replies), [], []

    def generate(self, models, prompt, kind, json_mode):
        self.asked.append(models[0])
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            self.attempts.append((models[0], 'ReadTimeout', 300.0))
            raise r
        self.attempts.append((models[0], 200, 12.5))
        return r, {}, models[0]


QIP = json.dumps({'category': 'qip', 'fields': [
    {'name': 'price_per_share', 'value': '165.65', 'quote': 'at the issue price of Rs. 165.65 per Equity Share'}]})


def test_lane_falls_back_and_leaves_out_a_model_that_keeps_timing_out():
    slow = RuntimeError('all nvidia read models busy or refused (moonshotai/kimi-k3: ReadTimeout)')
    c = FakeClient([slow, QIP, slow, QIP, QIP])
    lane = ar.Lane('main', ['nvidia:moonshotai/kimi-k3', 'nvidia:google/gemma-4-31b-it'], {'nvidia': c})
    assert lane.read('p')[1] == 'nvidia:google/gemma-4-31b-it'
    lane.read('p')
    assert lane.dropped == ['nvidia:moonshotai/kimi-k3']
    lane.read('p')
    assert c.asked == ['moonshotai/kimi-k3', 'google/gemma-4-31b-it'] * 2 + ['google/gemma-4-31b-it']
    use = ar.usage({'nvidia': c}, {'main': lane})
    assert use['models']['nvidia:google/gemma-4-31b-it'] == {'calls': 3, 'by_status': {'200': 3}, 'median_seconds_ok': 12.5}
    assert use['left_out_as_slow'] == {'main': ['nvidia:moonshotai/kimi-k3']}


def test_lanes_file_and_free_only_rule():
    spec = ar.lanes_of(ar.LANES_FILE.read_text(encoding='utf-8'))
    assert list(spec) == ['nvidia', 'zai', 'groq', 'gemini'] and all(spec.values())
    assert all({e.split(':', 1)[0] for e in es} == {name} for name, es in spec.items())   # one provider a lane
    assert ar.usable(['zai:glm-4.5-flash', 'zai:glm-5.3', 'nvidia:moonshotai/kimi-k3']) == [
        'zai:glm-4.5-flash', 'nvidia:moonshotai/kimi-k3']
    _, notes = ar.clients_for(['zai:glm-5.3'], env={'ZAI_API_KEY': 'k'})
    assert any('not one of zai' in n for n in notes)
    assert ar.clients_for(['nvidia:x'], env={})[1] == ['NVIDIA_API_KEY is not set; nvidia lanes skipped']
    assert isinstance(ar.clients_for(['gemini:gemini-3.5-flash-lite'], env={'GEMINI_API_KEY': 'k'})[0]['gemini'],
                      ar.GeminiCalls)


def _lanes(**replies):
    """Lanes named after their provider, each with a fake client answering in turn."""
    return {p: ar.Lane(p, [f'{p}:m'], {p: FakeClient(r)}) for p, r in replies.items()}


def _qips(n):
    return pd.DataFrame([_cand(f'nse:{i}', 'NSE', f'INE{i}', f'2026-10-13T1{i}:00:00+05:30', 'QIP') for i in range(1, n + 1)])


def test_lanes_read_different_filings_at_once_copy_the_same_file_and_cross_check_when_idle(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC if data != b'empty' else '', ['0.1 MB']))
    files = {'https://f/nse:1.pdf': b'one', 'https://f/nse:2.pdf': b'one', 'https://f/nse:3.pdf': b'empty'}
    lanes = _lanes(nvidia=[QIP, QIP], zai=[QIP, QIP])
    rows, notes = ar.run(_qips(3), lanes, None, 600, fetch=files.__getitem__, idle_wait=0.01)
    by = {r['event_id']: r for r in rows}
    # nse:1 and nse:2 are one file, taken by two lanes at once: the first downloaded is read, the other
    # waits for that read and is copied from it, never read twice
    read, copy = sorted((by['nse:1'], by['nse:2']), key=lambda r: r['status'] != 'read')
    assert read['status'] == 'read' and read['shown'] == 1 and json.loads(read['fields'])[0]['number'] == 165.65
    assert copy['status'] == 'same_file' and copy['same_as'] == read['event_id'] and copy['fields'] == read['fields']
    assert by['nse:3']['status'] == 'no_text'
    # the idle lane, of the other provider, read it again: its one shown value agrees
    other = ({'nvidia', 'zai'} - {read['reader'].split(':')[0]}).pop()
    assert read['second_reader'] == f'{other}:m' and json.loads(read['agreed']) == {'price_per_share': True}
    assert notes == {'not_reached': 0, 'cross_checked': 1} and len(rows) == 3
    assert sum(len(lane.clients[n].asked) for n, lane in lanes.items()) == 2   # one read, one cross-check
    r2 = FakeR2()
    assert ar.write(r2, rows, '2026-10-13', date(2026, 10, 13)) == 3
    clean = pd.read_parquet(io.BytesIO(r2.objects[ar.CLEAN_KEY]))
    assert set(clean['event_id']) == {'nse:1', 'nse:2', 'nse:3'} and 'exchange' in clean and 'category' in clean
    again = [dict(rows[-1], status='read', tries=2)]
    assert ar.write(r2, again, '2026-10-13', date(2026, 10, 13)) == 0   # replaced, not added


def test_a_filing_one_lane_cannot_read_goes_to_another_and_fails_only_when_all_have_tried(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC + data.decode(), []))   # different filings
    boom = RuntimeError('all nvidia read models busy or refused (x: HTTP 503)')
    lanes = _lanes(nvidia=[boom] * 9, zai=[QIP, QIP, boom])
    rows, notes = ar.run(_qips(3), lanes, None, 600, fetch=lambda u: u.encode(), idle_wait=0.01)
    by = {r['event_id']: r for r in rows}
    read = [r for r in rows if r['status'] == 'read']
    assert len(read) == 2 and all(r['reader_lane'] == 'zai' for r in read)
    failed = [r for r in rows if r['status'] == 'failed']
    assert len(failed) == 1 and 'nvidia:' in failed[0]['reason'] and 'zai:' in failed[0]['reason']
    assert failed[0]['tries'] == 1 and set(by) == {'nse:1', 'nse:2', 'nse:3'} and notes['not_reached'] == 0


def test_a_lane_at_its_daily_limit_stops_and_hands_its_work_on(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC + data.decode(), []))
    monkeypatch.setattr(ar, 'DAILY_CALLS', {'groq:m': 100})
    lanes = _lanes(groq=[QIP] * 5, zai=[QIP] * 5)
    lanes['groq'].used_today = {'groq:m': 95}            # 95% of 100 already used today
    assert lanes['groq'].models() == [] and lanes['zai'].models() == [('zai', 'm')]
    rows, _ = ar.run(_qips(3), lanes, None, 600, fetch=lambda u: u.encode(), idle_wait=0.01)
    assert [r['reader_lane'] for r in rows] == ['zai'] * 3 and lanes['groq'].clients['groq'].asked == []


def test_time_budget_leaves_the_rest_for_the_next_run(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC, []))
    ticks = iter([0, 0, 1000])                            # start, first take, then time is up
    rows, notes = ar.run(_qips(3), _lanes(nvidia=[QIP]), None, 600, fetch=lambda u: u.encode(),
                         now=lambda: next(ticks, 1000))
    assert len(rows) == 1 and notes['not_reached'] == 2


def test_each_filing_is_saved_as_it_is_read_and_a_failed_save_waits_for_the_next(monkeypatch):
    monkeypatch.setattr(ar.s, 'text_of', lambda data: (DOC + data.decode(), []))
    lanes, to_read = _lanes(nvidia=[QIP, QIP, QIP]), _qips(3)
    r2, calls, clock = FakeR2(), [], iter([0, 20, 20, 25, 50])

    def writer(r2_, rows, run_date, today):
        calls.append([r['event_id'] for r in rows])
        if len(calls) == 2:
            raise OSError('R2 down')
        return ar.write(r2_, rows, run_date, today)
    saver = ar.Saver(r2, '2026-10-13', date(2026, 10, 13), every=15, now=lambda: next(clock), writer=writer)
    rows, _ = ar.run(to_read, lanes, None, 600, fetch=lambda u: u.encode(), on_row=saver.add)
    # nse:1 saved at once; nse:2's save fails and is kept; nse:3 comes 5 s later and waits; the last write has both
    assert calls == [['nse:1'], ['nse:2']] and [r['event_id'] for r in saver.pending] == ['nse:2', 'nse:3']
    saver.flush(final=True)
    assert calls[-1] == ['nse:2', 'nse:3'] and saver.pending == [] and saver.added == 3 and saver.writes == 2
    clean = pd.read_parquet(io.BytesIO(r2.objects[ar.CLEAN_KEY]))
    assert sorted(clean['event_id']) == ['nse:1', 'nse:2', 'nse:3'] and len(rows) == 3


def test_the_last_save_of_a_run_raises():
    def writer(*_):
        raise OSError('R2 down')
    saver = ar.Saver(FakeR2(), '2026-10-13', date(2026, 10, 13), writer=writer)
    saver.add({'event_id': 'nse:1'})   # the first save fails quietly and keeps the row
    with pytest.raises(OSError):
        saver.flush(final=True)


@pytest.mark.parametrize('text,quote,ok', [
    ('Shivam Autotech sets ₹120 Cr rights issue at ₹12 per share', 'up to ₹ 12,000 Lakhs# ₹ 12 per Equity Share', True),
    ('Evonile Pharma approves rights issue of up to ₹900 Cr', 'for an aggregate amount not exceeding ₹9,000 million', True),
    ('16.45 lakh warrants at ₹152', 'up to 16,45,000 Warrants at an issue price of Rs. 152/-', True),
    ('FM Goetze approves ₹335 Cr capex', 'Investment Required Indian Rupees 3,351 Million', True),   # 335.1, rounded
    ('Sales up 32% in FY27', 'Sales FY 2026 812 FY 2027 1071', False),          # a growth rate of its own
    ('Raises ₹150 Cr', 'aggregating up to Rs. 25,00,40,000/-', False)])
def test_every_number_of_a_headline_or_point_must_be_in_its_quote(text, quote, ok):
    assert ar.numbers_backed(text, [quote]) is ok


def test_headline_points_and_year_ago_values_are_checked_against_the_filing():
    doc = ('the Board approved a Rights Issue of up to 10,00,00,000 Right Equity Shares. Issue Size up to ₹ 12,000 '
           'Lakhs. Issue Price ₹ 12 per Equity Share. Sales FY 2026 812 FY 2027 1071')
    out = {'category': 'rights', 'fields': [{'name': 'price_per_share', 'value': '12', 'quote': 'Issue Price ₹ 12 per Equity Share'}],
           'metrics': [{'label': 'Sales', 'period': 'Sep 2026', 'value': '1071', 'unit': 'units', 'quote': 'FY 2027 1071',
                        'previous': '812', 'previous_period': 'Sep 2025', 'previous_quote': 'FY 2026 812'}],
           'headline': {'text': 'Company sets ₹120 Cr rights issue at ₹12', 'quote': 'Issue Size up to ₹ 12,000 Lakhs'},
           'points': [{'text': 'Up to 10 Cr shares will be issued.', 'quote': 'up to 10,00,00,000 Right Equity Shares'},
                      {'text': 'Raising ₹500 Cr.', 'quote': 'Issue Size up to ₹ 12,000 Lakhs'},
                      {'text': 'Words the filing does not have.', 'quote': 'nowhere in it'}]}
    cat, fields, metrics = ar.validate(out, doc)
    metrics = [ar.with_previous(m, r, doc) for m, r in zip(metrics, out['metrics'])]
    headline, points = ar.card_words(out, doc, fields, metrics)
    assert headline['shown'] and [p['shown'] for p in points] == [True, False, False]
    assert points[1]['reason'] == 'a number not in its quote' and points[2]['reason'] == 'quote not found in the filing'
    assert metrics[0]['previous_number'] == 812 and metrics[0]['change_pct'] == 31.9   # our sum, not the model's
    assert 'headline' in ar.card_prompt({'exchange': 'NSE', 'symbol': 'X', 'subject': 's'}, doc).split('=== DOCUMENT ===')[0]

@pytest.mark.parametrize('day,parts', [(date(2026, 10, 13), ['year=2026/month=09', 'year=2026/month=10']),
                                       (date(2026, 1, 1), ['year=2025/month=12', 'year=2026/month=01'])])
def test_two_months_of_archive_are_read(day, parts):
    assert ar.months_back(day) == parts


@pytest.mark.parametrize('value,quote,cur', [
    ('809', 'for an equity consideration of US$ 809mn (including', 'USD'), ('1.4', 'generated c.US$ 1.4bn of revenue', 'USD'),
    ('165.65', 'at the issue price of Rs. 165.65 per', 'INR'), ('28,200.00', 'not exceeding ₹ 28,200.00 Lakhs', 'INR'),
    ('5', 'a price of C$ 5 a share', 'CAD'), ('2', 'S$ 2 million', 'SGD'), ('200.00', 'Total 200.00', None)])
def test_currency_comes_from_the_quote_never_assumed(value, quote, cur):
    assert ar.currency_in_quote(value, quote) == cur


def test_each_money_value_carries_its_own_or_the_filings_currency():
    doc = 'consideration of US$ 809mn for the stake. Currency: USD. Issue price 120 per share'
    _, fields, metrics = ar.validate({'fields': [
        {'name': 'amount', 'value': '809', 'quote': 'consideration of US$ 809mn for the stake'},
        {'name': 'amount_unit', 'value': 'million', 'quote': 'US$ 809mn'},
        {'name': 'currency', 'value': 'USD', 'quote': 'Currency: USD'},
        {'name': 'price_per_share', 'value': '120', 'quote': 'Issue price 120 per share'}],
        'metrics': [{'label': 'x', 'value': '809', 'unit': 'million', 'quote': 'consideration of US$ 809mn for the stake'}]}, doc)
    f = {x['name']: x for x in fields}
    assert f['amount']['currency'] == 'USD' and f['price_per_share']['currency'] == 'USD'   # the filing's currency
    assert metrics[0]['currency'] == 'USD'



def test_a_cross_check_compares_figures_by_number_whatever_their_labels():
    main = [{'label': 'Sales Sep 2026', 'number': 1071, 'shown': True}, {'label': 'Exports', 'number': 53, 'shown': True},
            {'label': 'held', 'number': 9, 'shown': False}]
    second = [{'label': 'Commercial vehicle sales', 'number': 1071, 'shown': True}, {'label': 'x', 'number': 54, 'shown': True}]
    assert ar.metric_agreement(main, second) == {'metric:0': True, 'metric:1': None}



def test_a_read_with_an_older_prompt_is_read_again_once_and_never_copied():
    today = date(2026, 10, 13)
    c = pd.DataFrame([_cand('nse:1', 'NSE', 'INE1', '2026-10-13T10:00:00+05:30', 'Buyback'),
                      _cand('nse:2', 'NSE', 'INE2', '2026-10-13T11:00:00+05:30', 'Buyback')])
    done = pd.DataFrame([{**c.iloc[0].to_dict(), 'status': 'read', 'tries': 1, 'prompt_version': 'live-1'},
                         {**c.iloc[1].to_dict(), 'status': 'read', 'tries': 1, 'prompt_version': ar.PROMPT_VERSION}])
    assert list(ar.choose(c, done, today)[0]['event_id']) == ['nse:1']
