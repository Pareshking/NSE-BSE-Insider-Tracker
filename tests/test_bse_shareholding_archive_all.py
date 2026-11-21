"""Every filing in BSE's shareholding list reaches the archive (raw coverage
audit, 21 Nov 2026: 10,863 of 24,558 filings in raw_v2/bse/shareholding_filings
were not in archive/bse_events/shareholding/; collectors/bse/events.shareholding
dropped the companies left to NSE before the merge). Each is archived with why
its XBRL was not read; the clean table is as before; a backfill re-reads the
lists kept in raw_v2 without asking BSE. Fixtures as in
test_bse_meetings_shareholding.py."""
from __future__ import annotations

import io
from datetime import date, datetime

import pandas as pd
from test_archive_and_writer import FakeR2
from test_bse_meetings_shareholding import BSE, SHP, js

from collectors.bse import events, parsers
from collectors.nse_events.run_daily import clean_shareholding
from insiders_clean import bse_events
from insiders_clean.raw_store import RawStore

VALENCIA = pd.DataFrame([{'isin': 'INE08RT01016', 'symbol': 'VALENCIA'}])   # an ISIN for NSE's shareholding table


def listed():
    return parsers.parse_shareholding_listing(js('shareholding_listing_20261012.json')['Table'])


def put_nse_table(r2, table):
    buf = io.BytesIO()
    table.to_parquet(buf, index=False)
    r2.objects[events.NSE_SHAREHOLDING] = buf.getvalue()


def run(r2, bse, master, day, history=True, max_xbrl=50, **kw):
    return events.run(events.Store(r2), bse, day, ('shareholding',), start=date(2025, 10, 8) if history else None,
                      master=master, max_xbrl=max_xbrl, now=datetime(day.year, day.month, day.day, 18, 0),
                      log=lambda *_: None, **kw)


def clean_table(r2):
    return pd.read_parquet(io.BytesIO(r2.objects['clean/current/bse_shareholding.parquet']))


def as_before(r2, master, nse):
    """The clean table as built before 21 Nov 2026: from the archive without the filings left to NSE (then never
    archived)."""
    arch = events.Store(r2).whole('shareholding')
    old = arch[arch['left_to_nse'].isna()].drop(columns='left_to_nse')
    out, _ = bse_events.clean(clean_shareholding(old), master, nse, 'shareholding')
    return out


def raw_objects(r2):
    return {k: v for k, v in r2.objects.items() if k.startswith('raw_v2/')}


def test_every_listed_filing_is_archived_with_its_status_and_the_clean_table_is_as_before(master):
    every = listed()
    for table in (None, VALENCIA):   # no NSE table: an NSE symbol leaves a company to NSE; with it, the ISIN
        r2, bse = FakeR2(), SHP()
        if table is not None:
            put_nse_table(r2, table)
        s = run(r2, bse, master, date(2026, 10, 12), max_xbrl=2)['streams']['shareholding']
        arch = events.Store(r2).whole('shareholding')
        assert len(arch) == len(every) and set(arch['event_id']) == set(every['event_id'])   # every line
        assert arch['xbrl_status'].notna().all()
        assert {'superseded', 'pending', 'no_xbrl', 'on_nse'} <= set(arch['xbrl_status'])
        left = arch[arch['left_to_nse'].notna()]
        want = {'542910'} if table is not None else {'533267', '500014'}   # Valencia; Cantabil and Utique
        assert set(left['bse_code']) == want and set(left['xbrl_status']) == {'on_nse'}
        assert set(left['left_to_nse']) == {events.LEFT_IN_TABLE if table is not None else events.LEFT_NSE_SYMBOL}
        assert not want & set(bse.files)   # their XBRL not read
        assert s['archived_left_to_nse'] == len(left) and s['fetched'] == len(every) - len(left)
        assert s['clean']['listed_left_to_nse_not_read'] == len(left)
        clean = clean_table(r2)
        assert 'left_to_nse' not in clean.columns and not want & set(clean['bse_code'])
        pd.testing.assert_frame_equal(clean, as_before(r2, master, table))


def test_a_filing_read_before_nse_had_its_company_keeps_what_was_read(master):
    """Valencia read from BSE, then NSE's table gains it: tonight's list marks it left to NSE; the archive keeps
    its parsed figures (merged again, not emptied) and the clean table leaves it out, as before."""
    r2, bse = FakeR2(), SHP()
    run(r2, bse, master, date(2026, 10, 12))
    put_nse_table(r2, VALENCIA)
    run(r2, bse, master, date(2026, 10, 13), history=False)
    assert bse.files.count('542910') == 1
    val = events.Store(r2).whole('shareholding').set_index('bse_code').loc['542910']
    assert val['left_to_nse'] == events.LEFT_IN_TABLE and val['xbrl_status'] == 'ok'
    assert val['promoter_holding_pct'] == 66.9215 and val['promoter_members'] == 18
    clean = clean_table(r2)
    assert '542910' not in set(clean['bse_code'])
    pd.testing.assert_frame_equal(clean, as_before(r2, master, VALENCIA))


def test_an_archive_from_before_the_column_cleans_as_before(master):
    arch = pd.DataFrame({'event_id': ['a'], 'xbrl_status': ['on_nse']})
    kept, left = bse_events.shareholding_input(arch)
    assert left == 0 and kept.equals(arch)


def test_backfill_from_raw_lists_adds_the_filings_the_archive_lacks_without_asking_bse(master):
    """--shp-from-raw: the lists kept in raw_v2 parsed again (no list call; raw only read). Filings already in the
    archive stay exactly as they are; the missing ones are added with their status. max_xbrl 0: no BSE call."""
    r2, bse = FakeR2(), SHP()
    RawStore(r2, collector='test').put('bse', 'shareholding_filings',
                                       (BSE / 'shareholding_listing_20261012.json').read_bytes(),
                                       url='https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w',
                                       content_type='application/json', covers={'flag': 6})
    RawStore(r2, collector='test').put('bse', 'shareholding_filings', b'{"Message":"error"}', status=500,
                                       url='https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w')
    run(r2, bse, master, date(2026, 10, 12))
    store = events.Store(r2)
    arch = store.whole('shareholding')   # rebuilt as the old run left it: Cantabil and Utique missing
    for k in [k for k in r2.objects if k.startswith(events.prefix('shareholding'))]:
        del r2.objects[k]
    store.merge('shareholding', arch[arch['left_to_nse'].isna()].drop(columns='left_to_nse'), '2026-10-12')
    before = store.whole('shareholding').set_index('event_id')
    clean_before, raw_before = clean_table(r2), raw_objects(r2)

    class NoBSE(SHP):
        def shareholding_filings(self, flag):
            raise AssertionError('from raw: no list call')

        def shareholding_xbrl(self, url, covers=None):
            raise AssertionError('max_xbrl 0: no XBRL call')

    out = []
    assert events.shp_from_raw_dry_run(store, print=out.append) == 0   # counts only
    assert '"would_add": 2' in out[0] and '"already_in_archive": 13' in out[0] and '"records_not_200": 1' in out[0]
    assert store.whole('shareholding').set_index('event_id').index.equals(before.index)
    s = run(r2, NoBSE(), master, date(2026, 11, 21), max_xbrl=0, shp_from_raw=True)['streams']['shareholding']
    assert s['from_raw']['lists_read'] == 1 and s['from_raw']['records_not_200'] == 1
    assert s['from_raw']['already_in_archive'] == 13 and s['added'] == 2 and s['archived_left_to_nse'] == 2
    after = store.whole('shareholding').set_index('event_id')
    assert set(after.index) == set(listed()['event_id'])
    left = after[after['left_to_nse'].notna()]
    assert set(left['bse_code']) == {'533267', '500014'} and set(left['xbrl_status']) == {'on_nse'}
    kept = after.loc[before.index]
    assert (kept['last_seen'] == before['last_seen']).all()   # rows already archived not touched
    assert (kept['xbrl_status'].astype(str) == before['xbrl_status'].astype(str)).all()
    assert raw_objects(r2) == raw_before   # raw only read
    pd.testing.assert_frame_equal(clean_table(r2), clean_before)
