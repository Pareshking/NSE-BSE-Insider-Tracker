"""Every raw row reaches the archive (owner, 21 Nov 2026), and the clean tables are exactly what they were.

Real exchange answers in tests/fixtures/: BSE SAST (Nov 2025), corporate actions (Oct 2025) and board meetings
(Feb 2026); NSE corporate actions, board meetings and tender offers (Oct 2026). tests/fixtures/bse/
sast_repeats_202511.json is built from sast_202511.json: real rows, each with a copy BSE could send in the same answer
(Company_Name with BSE's '-$', a blank diluted %, a copy equal in every field), the shape of the 119 rows the raw
coverage audit of 21 Nov found neither parsed nor dropped. Each collector is run twice on the same answers: as it is
now, and with its parsers as they were (kept rows only); the clean tables of the two runs are compared whole.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pandas as pd
import pytest
from conftest import FIXTURES
from test_archive_and_writer import FakeR2, parquet

from collectors.bse import events, parsers
from collectors.nse_events import parsers as nse_parsers
from insiders_clean import archive
from insiders_clean.raw_store import RawStore

BSE = FIXTURES / 'bse'
EV = FIXTURES / 'nse_events'


def js(path):
    return json.loads(path.read_text(encoding='utf-8'))


def frame(r2, key):
    return pd.read_parquet(io.BytesIO(r2.objects[key]))


def whole(r2, prefix):
    parts = [frame(r2, k) for k in sorted(r2.objects) if k.startswith(prefix) and k.endswith('.parquet')]
    return pd.concat(parts, ignore_index=True)


def legacy(monkeypatch, module, *names):
    """The parsers as they were before 21 Nov 2026: keep_all ignored, kept rows only."""
    for name in names:
        fn = getattr(module, name)
        monkeypatch.setattr(module, name, lambda *a, _fn=fn, keep_all=False, **k: _fn(*a, **k))


def same(a: pd.DataFrame, b: pd.DataFrame, key='event_id', check_dtype=True):
    a = a.sort_values(key).reset_index(drop=True)
    b = b.sort_values(key).reset_index(drop=True)
    assert list(a.columns) == list(b.columns)
    pd.testing.assert_frame_equal(a, b, check_dtype=check_dtype)


# --- the 119 BSE SAST rows ----------------------------------------------------------------------------------------------

def test_bse_sast_repeats_were_lost_uncounted_and_are_now_stored():
    rows = js(BSE / 'sast_repeats_202511.json')
    old, counts = parsers.parse_sast(rows)
    dropped = sum(counts['dropped_other_regulations'].values())
    identical = len(rows) - len({json.dumps(r, sort_keys=True) for r in rows})
    # before: parsed + dropped with a reason + identical copies fall short of the raw rows: the repeats vanished
    assert len(rows) - len(old) - dropped - identical == counts['repeats'] == 2
    new, _ = parsers.parse_sast(rows, keep_all=True)
    assert len(new) == len(rows) - identical and new['event_id'].is_unique
    pd.testing.assert_frame_equal(new[new['kept']].drop(columns=['kept', 'drop_reason']).reset_index(drop=True),
                                  old.reset_index(drop=True))
    out = new[~new['kept']]
    assert out['drop_reason'].value_counts().to_dict() == {parsers.SAST_REPEAT: 3, 'regulation 10(5) not kept (SAST_KEPT)': 1}
    # each repeat keeps its own row as sent and names the disclosure it repeats through it
    rep = out[out['drop_reason'] == parsers.SAST_REPEAT]
    origin = {parsers.sast_event_id(json.loads(j)) for j in rep['raw_json']}
    assert origin <= set(old['event_id']) | set(out['event_id'])
    assert any(json.loads(j)['Company_Name'].endswith('-$') for j in rep['raw_json'])


def test_sast_window_passes_on_every_distinct_row_with_the_kept_one_first():
    from test_bse import FakeSast
    rows = js(BSE / 'sast_repeats_202511.json')
    got = events.sast_window(FakeSast(rows), date(2025, 11, 1), date(2025, 11, 30), {})
    distinct = {json.dumps(r, sort_keys=True) for r in rows}
    assert {json.dumps(r, sort_keys=True) for r in got} <= distinct
    kept_before = {}
    for r in got:   # the collector's winner per disclosure (the last read) comes before its repeats
        kept_before.setdefault(parsers.sast_event_id(r), r)
    new, _ = parsers.parse_sast(got, keep_all=True)
    winners = new[new['kept']].set_index('event_id')['raw_json']
    assert all(winners[e] == parsers._raw(r) for e, r in kept_before.items() if e in winners.index)


# --- BSE events end to end ----------------------------------------------------------------------------------------------

class AllBSE:
    via, calls = 'requests', 0

    def __init__(self):
        self.sast_rows = js(BSE / 'sast_202511.json') + js(BSE / 'sast_repeats_202511.json')

    def sast(self, a, b):
        day = lambda r: pd.to_datetime(r['Acquisition_date'][:10], format='%d/%m/%Y').date()  # noqa: E731
        return [r for r in self.sast_rows if a <= day(r) <= b]

    def actions(self, a, b):
        return js(BSE / 'actions_20251008_20251015.json')

    def board_meetings(self, a, b):
        return js(BSE / 'board_meetings_202602.json') if a.month == 2 or b.month == 2 else {'Table': [], 'Table1': []}


def _bse_run(r2, master):
    for stream, start, end in (('sast', date(2025, 11, 1), date(2025, 11, 30)),
                               ('actions', date(2025, 10, 1), date(2025, 10, 31)),
                               ('meetings', date(2026, 2, 1), date(2026, 2, 28))):
        events.run(events.Store(r2), AllBSE(), date(2026, 3, 1), (stream,), start=start, end=end, master=master,
                   log=lambda *_: None)


def test_bse_events_archive_every_row_and_clean_tables_are_unchanged(master, monkeypatch):
    new_r2 = FakeR2()
    _bse_run(new_r2, master)
    with monkeypatch.context() as m:
        legacy(m, parsers, 'parse_sast', 'parse_actions', 'parse_board_meetings')
        old_r2 = FakeR2()
        _bse_run(old_r2, master)
    for stream in ('sast', 'actions', 'meetings'):
        same(frame(new_r2, f'clean/current/bse_{stream}.parquet'), frame(old_r2, f'clean/current/bse_{stream}.parquet'))
        arch_new, arch_old = whole(new_r2, f'archive/bse_events/{stream}/'), whole(old_r2, f'archive/bse_events/{stream}/')
        assert set(arch_old['event_id']) < set(arch_new['event_id'])          # nothing lost, the rest added
        out = arch_new[~archive.kept_mask(arch_new)]
        assert len(out) == len(arch_new) - len(arch_old) and out['drop_reason'].notna().all()
    acts = whole(new_r2, 'archive/bse_events/actions/')
    other = acts[~acts['kept'].astype(bool)]
    _, dropped = parsers.parse_actions(js(BSE / 'actions_20251008_20251015.json'))
    assert len(other) == dropped and set(other['purpose']) == {'other'} and other['subject'].str.len().gt(0).all()
    meetings = whole(new_r2, 'archive/bse_events/meetings/')
    assert (meetings.loc[~meetings['kept'].astype(bool), 'drop_reason'] == parsers.BM_NOT_KEPT).all()
    assert meetings.loc[~meetings['kept'].astype(bool), 'description'].str.len().gt(0).all()   # BSE's purpose text
    sast = whole(new_r2, 'archive/bse_events/sast/')
    assert set(sast.loc[~sast['kept'].astype(bool), 'drop_reason']) == {
        parsers.SAST_REPEAT, 'regulation 10(5) not kept (SAST_KEPT)', 'regulation 10(6) not kept (SAST_KEPT)'}
    rep = json.loads(new_r2.objects['clean/reports/bse_events/2026-03-01.json'])
    groups = parsers.parse_board_meetings(js(BSE / 'board_meetings_202602.json'))[1]['dropped_other_purposes']
    assert rep['streams']['meetings']['archived_not_kept'] == {parsers.BM_NOT_KEPT: groups}
    assert rep['streams']['meetings']['clean']['archive_not_kept'] == {parsers.BM_NOT_KEPT: groups}


def test_bse_meeting_rows_with_no_code_or_date_are_stored_alone():
    payload = js(BSE / 'board_meetings_202602.json')
    payload['Table'].append(dict(payload['Table'][0], scrip_code=None))
    payload['Table'].append(dict(payload['Table'][0], MEETING_BOARD_DATE=''))
    old, counts = parsers.parse_board_meetings(payload)
    new, counts2 = parsers.parse_board_meetings(payload, keep_all=True)
    assert counts == counts2
    pd.testing.assert_frame_equal(new[new['kept']].drop(columns=['kept', 'drop_reason']).reset_index(drop=True), old)
    alone = new[new['drop_reason'] == parsers.BM_NO_KEY]
    assert len(alone) == 2 and alone['event_id'].is_unique
    assert len(new) == len(old) + counts['dropped_other_purposes']


def test_a_meeting_with_no_kept_purpose_never_takes_the_place_of_a_kept_one():
    """Same scrip code and day, a later answer with only 'General': its own id, the kept meeting stays."""
    payload = js(BSE / 'board_meetings_202602.json')
    first = payload['Table'][0]
    kept, _ = parsers.parse_board_meetings({'Table': [first], 'Table1': []}, keep_all=True)
    other, _ = parsers.parse_board_meetings({'Table': [dict(first, PURPOSE_NAME='General')], 'Table1': []}, keep_all=True)
    arch, _ = archive.merge(None, kept, '2026-02-01', key='event_id')
    arch, _ = archive.merge(arch, other, '2026-02-02', key='event_id')
    assert len(arch) == 2 and kept['event_id'].iloc[0] != other['event_id'].iloc[0]
    view, out = archive.clean_view(arch)
    assert list(view['event_id']) == list(kept['event_id']) and out == {parsers.BM_NOT_KEPT: 1}


# --- NSE events end to end ----------------------------------------------------------------------------------------------

@pytest.fixture()
def nse_events(monkeypatch):
    import clean_writer
    from test_nse_events import FakeNSE

    from collectors.nse_events import run_daily

    class Resp:
        status_code = 200

        def __init__(self, path):
            self.content = path.read_bytes()

    monkeypatch.setattr(clean_writer.requests, 'get', lambda url, **kw: Resp(
        FIXTURES / ('nse_sme_sample.csv' if 'SME' in url else 'nse_equity_sample.csv')))
    return run_daily, FakeNSE


def test_nse_events_archive_every_row_and_clean_tables_are_unchanged(nse_events, monkeypatch):
    run_daily, FakeNSE = nse_events
    streams = ('actions', 'meetings', 'tenders')
    new_r2 = FakeR2()
    rep = run_daily.run(new_r2, FakeNSE(), date(2026, 10, 7), 10, streams=streams)
    with monkeypatch.context() as m:
        legacy(m, nse_parsers, 'parse_corporate_actions', 'parse_board_meetings')
        old_tenders = nse_parsers.parse_tender_offers
        m.setattr(nse_parsers, 'parse_tender_offers', lambda *a: old_tenders(*a).drop(columns=['bids_json']))
        old_r2 = FakeR2()
        run_daily.run(old_r2, FakeNSE(), date(2026, 10, 7), 10, streams=streams)
    for table in streams + ('buybacks',):
        same(frame(new_r2, f'clean/current/{table}.parquet'), frame(old_r2, f'clean/current/{table}.parquet'),
             key='buyback_id' if table == 'buybacks' else 'event_id')
    acts = whole(new_r2, 'archive/nse_events/actions/')
    _, dropped = nse_parsers.parse_corporate_actions(js(EV / 'corporate_actions.json'))
    other = acts[~acts['kept'].astype(bool)]
    assert len(other) == dropped and set(other['purpose']) == {'other'}
    assert set(other['drop_reason']) == {nse_parsers.ACTION_NOT_KEPT}
    assert rep['streams']['actions']['archived_not_kept'] == {nse_parsers.ACTION_NOT_KEPT: dropped}
    assert rep['streams']['actions']['fetched'] == len(acts) - dropped
    meet = whole(new_r2, 'archive/nse_events/meetings/')
    assert set(meet.loc[~meet['kept'].astype(bool), 'drop_reason']) == {nse_parsers.BM_NOT_KEPT}
    tenders = whole(new_r2, 'archive/nse_events/tenders/')
    assert tenders['bids_json'].notna().any()
    assert 'bids_json' not in frame(new_r2, 'clean/current/tenders.parquet')


def test_nse_meeting_rows_with_no_symbol_or_date_are_stored_not_lost():
    rows = js(EV / 'board_meetings.json')
    rows = rows['data'] if isinstance(rows, dict) else rows
    flagged = next(r for r in rows if 'result' in str(r.get('bm_desc', '')).lower() + str(r.get('bm_purpose', '')).lower())
    rows = rows + [dict(flagged, bm_symbol=None), dict(flagged, bm_symbol=None, bm_desc='Board Meeting - other')]
    old, n = nse_parsers.parse_board_meetings(rows)
    new, n2 = nse_parsers.parse_board_meetings(rows, keep_all=True)
    assert n == n2
    pd.testing.assert_frame_equal(new[new['kept']].drop(columns=['kept', 'drop_reason']).reset_index(drop=True),
                                  old.reset_index(drop=True))
    nokey = new[new['drop_reason'] == nse_parsers.BM_NO_KEY]
    assert len(nokey) == 1 and len(json.loads(nokey['raw_json'].iloc[0])) == 2   # both rows, one group, nothing lost


def test_archive_merge_keeps_a_lossless_copy_a_later_row_lacks():
    a = pd.DataFrame({'canonical_event_id': ['x'], 'v': ['1'], 'raw_json': ['{"Security_Name": "ABC LTD"}']})
    b = pd.DataFrame({'canonical_event_id': ['x'], 'v': ['2']})   # the nightly copy of the same deal
    arch, _ = archive.merge(None, a, '2026-11-01')
    arch, _ = archive.merge(arch, b, '2026-11-02')
    assert arch['v'].tolist() == ['2'] and arch['raw_json'].tolist() == ['{"Security_Name": "ABC LTD"}']


# --- new fields present -------------------------------------------------------------------------------------------------

def test_announcements_and_deals_carry_the_row_as_sent():
    from collectors.bse import announcements as bann
    from collectors.nse_events import announcements as nann
    n = js(EV / 'announcements.json')
    n = n['data'] if isinstance(n, dict) else n
    got = nann.parse(n, 'equities')
    assert [json.loads(j) for j in got['raw_json']] == [r for r in n if r]
    b = js(BSE / 'announcements.json')
    b = b['Table'] if isinstance(b, dict) else b
    got = bann.parse(b)
    assert {k for j in got['raw_json'] for k in json.loads(j)} >= {'ATTACHMENTNAME', 'NSURL'}
    deals = js(BSE / 'bulk_history_20261009.json')['Table']
    import r2_writer
    rows = parsers.deal_rows(deals)
    assert [json.loads(r['raw_json']) for r in rows] == deals
    no_copy = [{k: v for k, v in r.items() if k != 'raw_json'} for r in rows]
    assert [r2_writer.canonical_event_id('bse', 'bulk_deals', r) for r in rows] == \
        [r2_writer.canonical_event_id('bse', 'bulk_deals', r) for r in no_copy]


def test_index_close_keeps_every_column():
    from insiders_clean import index_close
    from test_index_close import BODY
    df = index_close.parse_index(BODY)
    r = df[df['symbol'] == 'Nifty 500'].iloc[0]
    assert (r['points_change'], r['change_pct'], r['pe'], r['pb'], r['div_yield']) == (189.45, 0.79, 24.69, 3.75, 1.14)


def test_udiff_columns_left_out_are_in_their_own_table():
    from insiders_clean import prices
    from test_prices import HEAD, ROW, _csv
    body = _csv(ROW, ROW.replace('ABC', 'XYZ').replace('INE000A01010', 'INE000B01010'))
    extra = prices.udiff_extra(body, 'NSE')
    assert len(extra) == 2 and set(HEAD.split(',')) == set(prices._MAP) | (set(extra.columns) - {
        'date', 'exchange', 'isin', 'symbol', 'series', 'line'})
    assert extra.loc[0, 'SsnId'] == 'F1' and extra.loc[0, 'NewBrdLotQty'] == '1' and extra.loc[0, 'Sgmt'] == 'CM'


def pr_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('bc081026.csv', 'SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,'
                                   'PURPOSE\r\nEQ,ABC,ABC LTD,,,,09-OCT-2026,,,"DIVIDEND - RS 2, PER SHARE"\r\n')
        z.writestr('an081026.txt', 'NSE announcements of the day\r\nABC: Board meeting\r\n')
        z.writestr('MCAP08102026.csv', 'Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,'
                                       'Face Value(Rs.),Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)\n'
                                       '08 OCT 2026,ABC,EQ,ABC LTD,Listed,08 OCT 2026,5.00,100,10.00,1000.00\n')
    return buf.getvalue()


def test_pr_zip_members_line_by_line():
    from insiders_clean import market_cap
    got = market_cap.pr_members(pr_zip(), '2026-10-08')
    assert set(got) == {'bc_csv', 'an_txt', 'mcap_csv'}
    bc = got['bc_csv']
    assert bc.loc[1, 'PURPOSE'] == 'DIVIDEND - RS 2, PER SHARE' and bc.loc[1, 'EX_DT'] == '09-OCT-2026'
    assert got['an_txt']['text'].str.rstrip('\r').tolist() == ['NSE announcements of the day', 'ABC: Board meeting']
    assert got['mcap_csv'].loc[1, 'Last Trade Date'] == '08 OCT 2026'   # the column parse_mcap leaves out


def test_price_backfill_writes_the_extras_and_extras_only_leaves_the_layer(monkeypatch):
    import price_backfill as pb
    from test_price_backfill import Resp
    from test_prices import ROW, _csv

    class R2(FakeR2):   # as boto3 says it: price_backfill reads a missing month by the error's text
        def get_object(self, Bucket, Key):
            if Key not in self.objects:
                raise KeyError('NoSuchKey')
            return super().get_object(Bucket, Key)
    r2 = R2()

    def resp(url):
        if 'PR081026' in url:
            return Resp(200, pr_zip(), 'application/zip')
        return Resp(200, _csv(ROW)) if '20261008' in url else Resp(404, b'x')
    monkeypatch.setattr(pb.requests, 'Session', lambda: type('S', (), {'headers': {}, 'get': lambda self, u, timeout=0: resp(u)})())
    t = pb.run(date(2026, 10, 8), date(2026, 10, 8), ['NSE', 'NSE_PR'], r2, 'b', sleep=lambda s: None)
    assert t['NSE']['extras_written'] == {'prices/udiff_extra/nse/2026-10.parquet': 1}
    assert set(t['NSE_PR']['extras_written']) == {f'archive/nse_pr/{k}/2026-10.parquet' for k in ('bc_csv', 'an_txt', 'mcap_csv')}
    layer = r2.objects['prices/daily/nse/2026-10.parquet']
    r2.objects.pop('archive/nse_pr/bc_csv/2026-10.parquet')
    t = pb.run(date(2026, 10, 8), date(2026, 10, 8), ['NSE', 'NSE_PR'], r2, 'b', sleep=lambda s: None, extras_only=True)
    assert 'archive/nse_pr/bc_csv/2026-10.parquet' in r2.objects and r2.objects['prices/daily/nse/2026-10.parquet'] == layer
    assert t['NSE']['already'] == 0 and t['NSE']['sessions'] == 1


# --- re-reading raw_v2 into the archive ---------------------------------------------------------------------------------

T = pd.Timestamp('2026-11-01T10:00:00Z').to_pydatetime()


def _raw(r2, source, dataset, body, covers=None, url='https://example.invalid/api', ct='application/json'):
    RawStore(r2, bucket='b', collector='test', clock=lambda: T).put(source, dataset, body, url=url, content_type=ct,
                                                                     covers=covers)


def test_reparse_adds_only_rows_the_clean_tables_leave_out(master):
    import raw_reparse
    r2 = FakeR2()
    acts = js(BSE / 'actions_20251008_20251015.json')
    sast = js(BSE / 'sast_repeats_202511.json')
    _raw(r2, 'bse', 'corporate_actions', json.dumps(acts).encode())
    _raw(r2, 'bse', 'sast', json.dumps(sast).encode())
    _raw(r2, 'bse', 'board_meetings', json.dumps(js(BSE / 'board_meetings_202602.json')).encode())
    # the archives as the collector wrote them before 21 Nov 2026: kept rows only; one kept action never stored
    old_acts, dropped = parsers.parse_actions(acts)
    r2.objects['archive/bse_events/actions/year=2025.parquet'] = parquet(
        archive.merge(None, old_acts.iloc[1:], '2025-10-20', key='event_id')[0])
    r2.objects['archive/bse_events/sast/year=2025.parquet'] = parquet(
        archive.merge(None, parsers.parse_sast(sast)[0], '2025-11-20', key='event_id')[0])
    old_meet, mc = parsers.parse_board_meetings(js(BSE / 'board_meetings_202602.json'))
    r2.objects['archive/bse_events/meetings/year=2026.parquet'] = parquet(
        archive.merge(None, old_meet, '2026-02-20', key='event_id')[0])
    before = {s: whole(r2, f'archive/bse_events/{s}/') for s in ('actions', 'sast', 'meetings')}
    dry = raw_reparse.run(r2, ['bse_actions', 'bse_sast', 'bse_meetings'], dry=True, run_date='2026-11-21')
    assert all(whole(r2, f'archive/bse_events/{s}/').equals(before[s]) for s in before)   # a dry run writes nothing
    rep = raw_reparse.run(r2, ['bse_actions', 'bse_sast', 'bse_meetings'], run_date='2026-11-21')
    assert dry['targets']['bse_actions']['added'] == rep['targets']['bse_actions']['added'] == dropped
    assert rep['targets']['bse_actions']['kept_not_archived'] == 1      # counted, never added
    assert rep['targets']['bse_sast']['added'] == 4 and rep['targets']['bse_sast']['kept_not_archived'] == 0
    assert rep['targets']['bse_meetings']['added'] == mc['dropped_other_purposes']   # meetings with no kept purpose
    for s in before:
        after = whole(r2, f'archive/bse_events/{s}/')
        view, _ = archive.clean_view(after)
        old_view, _ = archive.clean_view(before[s])
        # what the clean tables read: the same rows and values (first_seen is stored as text either way)
        same(view, old_view, check_dtype=False)
        assert (after[~archive.kept_mask(after)]['first_seen'] == '2026-11-21').all()
        assert set(before[s]['event_id']) < set(after['event_id'])
    again = raw_reparse.run(r2, ['bse_actions', 'bse_sast', 'bse_meetings'], run_date='2026-11-22')
    assert all(t.get('added', 0) == 0 for t in again['targets'].values())   # a rerun adds nothing


def test_reparse_fills_lossless_copies_and_builds_own_tables():
    import raw_reparse
    from collectors.bse import announcements as bann
    from test_prices import ROW, _csv
    r2 = FakeR2()
    b = js(BSE / 'announcements.json')
    _raw(r2, 'bse', 'announcements', json.dumps(b).encode())
    old = bann.parse(b['Table'] if isinstance(b, dict) else b).drop(columns=['raw_json'])
    r2.objects['archive/announcements/bse/year=2026/month=10.parquet'] = parquet(
        archive.merge(None, old, '2026-10-12', key='event_id')[0])
    deals = js(BSE / 'bulk_history_20261009.json')
    _raw(r2, 'bse', 'bulk_deals_history', json.dumps(deals).encode())
    import r2_writer
    canon, _ = r2_writer.rows_to_parquet_bytes('bse', 'bulk_deals', [
        {k: v for k, v in r.items() if k != 'raw_json'} for r in parsers.deal_rows(deals['Table'])])
    r2.objects['archive/canonical/bse/bulk_deals/year=2026/quarter=4.parquet'] = parquet(
        archive.merge(None, pd.read_parquet(io.BytesIO(canon)), '2026-10-10')[0])
    _raw(r2, 'exchange_files', 'nse_udiff_cm', _csv(ROW), covers={'day': '2026-10-08'}, ct='text/csv')
    _raw(r2, 'exchange_files', 'nse_pr_zip', pr_zip(), covers={'day': '2026-10-08'}, ct='application/zip')
    _raw(r2, 'nse', 'tenders', (EV / 'tender_offers_active.json').read_bytes())   # the open offers carry the bid book
    tenders = nse_parsers.parse_tender_offers([], js(EV / 'tender_offers_active.json')).drop(columns=['bids_json'])
    r2.objects['archive/nse_events/tenders/year=2026.parquet'] = parquet(
        archive.merge(None, tenders, '2026-10-07', key='event_id')[0])
    before_ann = frame(r2, 'archive/announcements/bse/year=2026/month=10.parquet')
    rep = raw_reparse.run(r2, ['bse_announcements', 'bse_bulk_deals', 'udiff_nse', 'nse_pr', 'nse_tenders'],
                          run_date='2026-11-21')
    t = rep['targets']
    assert t['bse_announcements']['filled'] == len(old) and t['bse_announcements'].get('added', 0) == 0
    ann = frame(r2, 'archive/announcements/bse/year=2026/month=10.parquet')
    assert ann['raw_json'].notna().all()
    pd.testing.assert_frame_equal(ann.drop(columns=['raw_json']), before_ann,   # every other value and date as it was
                                  check_dtype=False)
    assert t['bse_bulk_deals']['filled'] == len(deals['Table'])
    stored = frame(r2, 'archive/canonical/bse/bulk_deals/year=2026/quarter=4.parquet')
    assert {json.loads(j)['CLIENT_NAME'] for j in stored['raw_json']} == {r['CLIENT_NAME'] for r in deals['Table']}
    assert t['udiff_nse']['lines_added'] == 1
    assert frame(r2, 'prices/udiff_extra/nse/2026-10.parquet').loc[0, 'SsnId'] == 'F1'
    assert t['nse_pr']['lines_added'] == 2 + 2 + 2 and 'archive/nse_pr/bc_csv/2026-10.parquet' in r2.objects
    assert t['nse_tenders']['filled'] > 0
    assert frame(r2, 'archive/nse_events/tenders/year=2026.parquet')['bids_json'].notna().any()
    assert all('failed' not in s for s in t.values())
