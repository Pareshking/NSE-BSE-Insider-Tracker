"""BSE board meetings and shareholding patterns: client calls, parsers, the
NSE link, moved meetings, the XBRL catch-up, and the trading window for a
BSE-only company.

Fixtures in tests/fixtures/bse/ are real BSE answers, trimmed: board meetings
with meeting dates in Feb 2026 (34 meetings, among them 11 of companies in
NSE's own Feb 2026 fixture, and two moved meetings with their old dates in
Table1), the shareholding filings list of 12 Oct 2026 (plus Tulasee Bio
Ethanol's year, with a revised March 2026 filing, and an old filing BSE
marks IsXBRL 0), and three filings' inline XBRL, gzip-compressed: Valencia
Nutrition (542910, 18 promoter-group members), Netripples Software (542117,
2 members) and Utique Enterprises (500014, no promoter group).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import date, datetime

import pandas as pd
import pytest
from conftest import FIXTURES
from test_archive_and_writer import FakeR2
from test_bse import FakeHTTP, FakeRaw, Resp, client

from collectors.bse import events, parsers
from collectors.bse.client import Missing
from collectors.nse_events import parsers as nse_parsers
from insiders_clean import bse_events, trading_window
from insiders_clean.calendar import Calendar

BSE = FIXTURES / 'bse'
XBRL = {'542910': 'shp_542910_20260930.html.gz', '542117': 'shp_542117_20260930.html.gz',
        '500014': 'shp_500014_20260930.html.gz'}


def js(name):
    return json.loads((BSE / name).read_text(encoding='utf-8'))


def xbrl(code) -> bytes:
    return gzip.decompress((BSE / XBRL[code]).read_bytes())


def meetings():
    return parsers.parse_board_meetings(js('board_meetings_202602.json'))


def nse_meetings():
    m, _ = nse_parsers.parse_board_meetings(json.loads((FIXTURES / 'nse_events' / 'board_meetings_past.json')
                                                       .read_text(encoding='utf-8')))
    return m


# --- client ----------------------------------------------------------------------

def test_meeting_and_shareholding_endpoints():
    http, raw = FakeHTTP(body=b'{"Table": [], "Table1": []}'), FakeRaw()
    c = client(http, raw=raw)
    assert c.board_meetings(date(2026, 2, 1), date(2026, 2, 28)) == {'Table': [], 'Table1': []}
    http.body = b'{"Table": []}'
    assert c.shareholding_filings(6) == []
    (u0, p0), (u1, p1) = http.calls
    assert u0.endswith('boardmeeting_fno/w') and p0 == {'securityName': '', 'txtDate': '01/02/2026', 'txtTodate': '28/02/2026',
                                                        'ddlPurpose': '', 'ddlindustry': '', 'ddlsegment': 'C'}
    assert u1.endswith('Corp_Shareholding_ng/w') and p1 == {'scripcode': '', 'flag': '6', 'indtype': ''}
    assert [d for _, d, _ in raw.puts] == ['board_meetings', 'shareholding_filings']


def test_xbrl_file_kept_gzipped_with_its_hash_and_a_404_is_that_file_only():
    body = xbrl('542910')
    http, raw = FakeHTTP(body=body), FakeRaw()
    c = client(http, raw=raw)
    assert c.shareholding_xbrl('/XBRLFILES/SHPXBRLDataXML/542910_12102026182749_SP.html') == body
    assert http.calls[0][0] == 'https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/542910_12102026182749_SP.html'
    (_, dataset, kw), = raw.puts
    assert dataset == 'shareholding_xbrl' and kw['content_type'] == 'application/gzip'
    assert kw['params']['sha256_as_sent'] == hashlib.sha256(body).hexdigest()
    with pytest.raises(Missing):
        client(FakeHTTP(script={0: Resp(404, b'not found', 'text/html')})).shareholding_xbrl('/XBRLFILES/x.html')


# --- board meetings ------------------------------------------------------------------

def test_board_meetings_flags_moved_dates_and_drops():
    df, counts = meetings()
    assert counts == {'dropped_other_purposes': 4, 'moved_dates': 2}   # 'General' and authorised capital only
    assert df['event_id'].is_unique and not df['fund_raising'].any()   # BSE's purpose list has no fund raising
    warrants = df[df['description'].eq('Quarterly Results | Issue Of Warrants')].iloc[0]
    assert warrants['preferential'] and warrants['results']
    assert set(df.loc[df['description'].str.contains('Right Issue'), 'purposes'].str.contains('rights')) == {True}
    centum = df[df['bse_code'] == '517544'].set_index('moved')
    assert centum.loc[False, 'meeting_date'] == date(2026, 2, 14)
    assert centum.loc[True, 'meeting_date'] == date(2026, 2, 6)
    assert centum.loc[True, 'intimation_ts'] == '2026-01-30T14:32:00'   # 'Jan 30 2026  2:32PM'


def test_meetings_link_to_nse_and_moved_dates_drop_what_they_replace(master):
    df, _ = meetings()
    old = df[(df['bse_code'] == '517544') & df['moved']].iloc[0]
    # the meeting as first listed (06 Feb, intimated 20 Jan), before it was moved
    first = old.copy()
    first['moved'], first['intimation_ts'], first['event_id'] = False, '2026-01-20T10:00:00', 'first-centum'
    arch = pd.concat([df, first.to_frame().T], ignore_index=True)
    nse = nse_meetings()
    clean, counts = bse_events.clean(arch, master, nse, 'meetings')
    assert counts['moved_away'] == 1 and not clean['moved'].astype(bool).any()
    assert set(clean.loc[clean['bse_code'] == '517544', 'meeting_date']) == {date(2026, 2, 14)}
    linked = clean[clean['on_nse']]
    assert len(linked) >= 5 and (linked['listed_on'] == 'bse,nse').all()
    for _, r in linked.iterrows():   # same ISIN and day in NSE's table
        assert ((nse['isin'] == r['isin']) & (nse['meeting_date'] == r['meeting_date'])).any()
    pages = bse_events.with_bse(nse, clean)
    key = pages['isin'].astype(str) + pages['meeting_date'].astype(str)
    assert not key[pages['isin'].notna()].duplicated().any()   # a meeting on both exchanges shows once
    assert (pages['listed_on'] == 'bse').sum() == counts['bse_only']


def test_meetings_history_runs_ahead_and_resumes(master):
    r2, calls = FakeR2(), []

    class BM:
        via, calls_n = 'requests', 0

        def board_meetings(self, a, b):
            calls.append((a, b))
            return js('board_meetings_202602.json') if a.month == 2 else {'Table': [], 'Table1': []}

    bse = BM()
    bse.calls = 0
    rep = events.run(events.Store(r2), bse, date(2026, 2, 10), ('meetings',), start=date(2026, 1, 1), master=master,
                     log=lambda *_: None)
    assert calls[-1][1] == date(2026, 4, 11)   # 60 days past today
    s = rep['streams']['meetings']
    assert s['moved_dates'] == 2 and s['clean']['rows'] > 0 and 'clean/current/bse_meetings.parquet' in r2.objects
    calls.clear()
    events.run(events.Store(r2), bse, date(2026, 2, 10), ('meetings',), start=date(2026, 1, 1), master=master,
               log=lambda *_: None)
    assert calls == []


def test_results_date_of_a_bse_only_company_reaches_its_trades(master):
    """A BSE-only company (no NSE symbol): its BSE results meeting dates the
    trading window of its insider trades, joined by ISIN."""
    df, _ = meetings()
    clean, _ = bse_events.clean(df, master, nse_meetings(), 'meetings')
    row = clean[~clean['on_nse'] & clean['results'] & clean['nse_symbol'].isna() & clean['isin'].notna()].iloc[0]
    pages = bse_events.with_bse(nse_meetings(), clean)
    day = (pd.Timestamp(row['meeting_date']) + pd.Timedelta(days=2)).date()
    t = pd.DataFrame([{'isin': row['isin'], 'nse_symbol': None, 'trade_date_from': day, 'trade_date_to': day,
                       'side': 'BUY', 'is_market': True}])
    out, rep = trading_window.attach(t, pages, Calendar([d.date() for d in pd.bdate_range('2025-01-01', '2026-12-31')]))
    assert out.loc[0, 'results_date'] == row['meeting_date'] and out.loc[0, 'window_open_buy']
    assert rep['window_open_buys'] == 1


# --- shareholding --------------------------------------------------------------------

def test_listing_and_inline_xbrl_read_with_nse_parsers():
    sh = parsers.parse_shareholding_listing(js('shareholding_listing_20261012.json')['Table'])
    tul = sh[sh['bse_code'] == '524514'].set_index('quarter_id')
    assert tul.loc['129.01', 'revised'] and not tul.loc['129.00', 'revised']
    assert sh.loc[sh['bse_code'] == '527007', 'xbrl_url'].isna().all()   # IsXBRL 0
    val = nse_parsers.parse_shp_xbrl(parsers.ixbrl_facts(xbrl('542910').decode()))
    assert val['promoter_holding_pct_xbrl'] == 66.9215 and val['total_shares'] == 19_840_341
    assert val['public_holding_pct_xbrl'] == 33.0785 and val['promoter_pledge_pct'] == 0
    members, check = nse_parsers.parse_shp_members(parsers.ixbrl_facts(xbrl('542910').decode()))
    assert check == {'members': 18, 'member_shares': 13_277_454.0, 'promoter_shares': 13_277_454.0, 'check': 'match'}
    assert members[0]['member_name_filed'] == 'MANISH PRAVINCHANDRA TURAKHIA' and members[0]['pct_of_company'] == 39.85
    assert {m['sub_category'] for m in members} >= {'Individual or HUF', 'Bodies Corporate'}
    ut = nse_parsers.parse_shp_xbrl(parsers.ixbrl_facts(xbrl('500014').decode()))
    assert ut['no_promoter_group'] and ut['promoter_shares'] == 0 and ut['public_holding_pct_xbrl'] == 94.0426


class SHP:
    """Shareholding list from the fixture; XBRL for the three fixture filings, 404 otherwise."""

    def __init__(self):
        self.via, self.calls, self.files = 'requests', 0, []

    def shareholding_filings(self, flag):
        self.flag = flag
        return js('shareholding_listing_20261012.json')['Table']

    def shareholding_xbrl(self, url, covers=None):
        code = url.rsplit('/', 1)[1].split('_')[0]
        self.files.append(code)
        if code not in XBRL:
            raise Missing(f'HTTP 404 from {url}')
        return xbrl(code)


def test_shareholding_bse_only_catch_up_members_and_clean(master):
    r2, bse = FakeR2(), SHP()
    now = datetime(2026, 10, 12, 18, 0)
    rep = events.run(events.Store(r2), bse, date(2026, 10, 12), ('shareholding',), start=date(2025, 10, 8),
                     master=master, max_xbrl=2, now=now, log=lambda *_: None)
    s = rep['streams']['shareholding']
    assert bse.flag == events.SHP_FLAG_HISTORY and s['dual_listed_skipped'] == 2   # Cantabil, Utique (APPLEIND)
    assert s['xbrl_fetched'] == 2 and s['xbrl_status']['pending'] >= 1 and s['xbrl_status']['superseded'] == 1
    arch = events.Store(r2).whole('shareholding')
    assert '533267' not in set(arch['bse_code'])   # dual-listed: NSE's collector has it
    # a second run reads the pending ones (404s fail per file) and keeps what was parsed
    rep2 = events.run(events.Store(r2), bse, date(2026, 10, 12), ('shareholding',), master=master, max_xbrl=50,
                      now=datetime(2026, 10, 13, 18, 0), log=lambda *_: None)
    s2 = rep2['streams']['shareholding']
    assert bse.flag == events.SHP_FLAG_NIGHTLY and s2['xbrl_status']['ok'] == 2 and s2['xbrl_status']['failed'] >= 1
    assert bse.files.count('542910') == 1   # each file read once
    clean = pd.read_parquet(io.BytesIO(r2.objects['clean/current/bse_shareholding.parquet']))
    val = clean[clean['bse_code'] == '542910'].iloc[0]
    assert val['symbol'] == '542910' and val['isin'] == 'INE08RT01016' and val['listed_on'] == 'bse'
    assert val['promoter_holding_pct'] == 66.9215 and val['public_holding_pct'] == 33.0785
    assert val['members_check'] == 'match' and val['promoter_members'] == 18
    assert set(clean['bse_code']) == {'542910', '542117'}   # parsed only; the failed filings hold no figure
    assert s2['clean']['not_parsed_yet'] >= 1
    group = pd.read_parquet(io.BytesIO(r2.objects['clean/current/bse_promoter_group.parquet']))
    assert len(group) == 20 and set(group.loc[group['symbol'] == '542910', 'isin']) == {'INE08RT01016'}
    assert sum(k.startswith(events.GROUP_BATCHES) for k in r2.objects) == 2   # one write-once batch a run


def test_shareholding_dry_run_reads_without_writing():
    bse = SHP()
    rep = events.run(None, bse, date(2026, 10, 12), ('shareholding',), max_xbrl=1, log=lambda *_: None)
    s = rep['streams']['shareholding']
    assert rep['dry_run'] and s['listed'] == 15 and s['xbrl_fetched'] == 1


# --- added when the WIP landed on main (22 Oct 2026) ---------------------------------

def test_meetings_window_reads_whole_and_pieces_and_unites_them():
    """22 Oct 2026, live: October 2026 asked as one month answered 892 meetings,
    its halves 916 (24 recent listings missing from the month call). A window is
    read whole and in 15-day pieces; rows only one reading had are counted."""
    rows = js('board_meetings_202602.json')
    calls = []

    class BM:
        def board_meetings(self, a, b):
            calls.append((a, b))
            whole = (a, b) == (date(2026, 2, 1), date(2026, 2, 28))
            t = rows['Table'][:-3] if whole else [r for r in rows['Table']
                                                  if a.isoformat() <= r['MEETING_BOARD_DATE'][:10] <= b.isoformat()]
            return {'Table': t, 'Table1': rows['Table1'] if whole else []}

    stats = {}
    got = events.meetings_window(BM(), date(2026, 2, 1), date(2026, 2, 28), stats)
    assert calls == [(date(2026, 2, 1), date(2026, 2, 28)), (date(2026, 2, 1), date(2026, 2, 15)),
                     (date(2026, 2, 16), date(2026, 2, 28))]
    assert len(got['Table']) == len(rows['Table']) and len(got['Table1']) == len(rows['Table1'])
    assert stats['calls'] == 3 and stats['rows_only_in_pieces'] == 3
    assert stats['rows_only_in_whole_window'] == len(rows['Table1'])
    stats = {}
    events.meetings_window(BM(), date(2026, 2, 1), date(2026, 2, 10), stats)   # shorter than a piece: one call
    assert stats == {'calls': 1}


def test_dataset_argument_takes_a_comma_list():
    assert events.datasets('all') == events.STREAMS
    assert events.datasets('shareholding,meetings') == ('meetings', 'shareholding')
    with pytest.raises(Exception):
        events.datasets('meetings,results')


def test_shareholding_gets_nse_columns_investor_types_and_pct_of_sebi_base(master):
    r2, bse = FakeR2(), SHP()
    events.run(events.Store(r2), bse, date(2026, 10, 12), ('shareholding',), start=date(2025, 10, 8),
               master=master, max_xbrl=50, now=datetime(2026, 10, 12, 18, 0), log=lambda *_: None)
    clean = pd.read_parquet(io.BytesIO(r2.objects['clean/current/bse_shareholding.parquet']))
    nse_cols = set(nse_parsers.SH_COLUMNS) | {'promoter_shares', 'total_shares', 'promoter_pledge_pct',
                                             'promoter_encumbered_pct', 'no_promoter_group', 'shareholding_stale',
                                             'members_status', 'members_check', 'categories_status',
                                             'categories_check', 'categories_unmapped', 'dr_shares', 'pct_base_shares'}
    nse_cols |= {f'{t}_{k}' for t in nse_parsers.SHP_CATEGORIES for k in ('shares', 'pct')}
    assert nse_cols <= set(clean.columns)
    val = clean[clean['bse_code'] == '542910'].iloc[0]
    assert val['categories_status'] == 'ok' and val['categories_check'] == 'match' and pd.isna(val['categories_unmapped'])
    assert val['promoter_pct'] == val['promoter_holding_pct'] == 66.9215 and val['pct_base_shares'] == 19_840_341
    assert val['retail_pct'] == 5.0753
    total = sum(val[f'{t}_shares'] for t in nse_parsers.SHP_CATEGORIES) + val['dr_shares']
    assert total == val['total_shares']
    # Utique (no promoter group, 5.9574% in an employee trust): what NSE's listing calls employee_trust_pct
    rows = pd.DataFrame([{'pct_base_shares': 55_673_122.0, 'non_public_other_pct': 5.9574}])
    got = nse_parsers.parse_shp_xbrl(parsers.ixbrl_facts(xbrl('500014').decode()))
    events._holding_pcts(rows, 0, got)
    assert rows.at[0, 'promoter_holding_pct'] == 0 and rows.at[0, 'employee_trust_pct'] == 5.9574
    assert rows.at[0, 'public_holding_pct'] == 94.0426


def test_shareholding_of_a_company_in_nse_table_is_left_to_nse(master):
    """Valencia Nutrition has no NSE symbol in the master; once its ISIN is in
    NSE's shareholding table it is NSE's, neither read nor shown from BSE."""
    r2, bse = FakeR2(), SHP()
    nse = pd.DataFrame([{'event_id': 'n1', 'symbol': 'VALENCIA', 'isin': 'INE08RT01016',
                         'quarter_end': pd.Timestamp('2026-09-30'), 'promoter_holding_pct': 66.92}])
    buf = io.BytesIO()
    nse.to_parquet(buf, index=False)
    r2.objects[events.NSE_SHAREHOLDING] = buf.getvalue()
    rep = events.run(events.Store(r2), bse, date(2026, 10, 12), ('shareholding',), start=date(2025, 10, 8),
                     master=master, max_xbrl=50, now=datetime(2026, 10, 12, 18, 0), log=lambda *_: None)
    s = rep['streams']['shareholding']
    assert s['isin_in_nse_table_skipped'] == 1 and '542910' not in bse.files
    clean = pd.read_parquet(io.BytesIO(r2.objects['clean/current/bse_shareholding.parquet']))
    assert '542910' not in set(clean['bse_code'])
    # a row read before NSE had the company is left out by the clean step, and counted
    arch = events.Store(r2).whole('shareholding')
    row = arch[arch['bse_code'] == '542117'].iloc[[0]].assign(bse_code='542910', event_id='x', symbol='542910')
    from collectors.nse_events.run_daily import clean_shareholding
    out, counts = bse_events.clean(clean_shareholding(pd.concat([arch, row], ignore_index=True)), master, nse,
                                   'shareholding')
    assert counts['isin_in_nse_table_left_out'] == 1 and '542910' not in set(out['bse_code'])
