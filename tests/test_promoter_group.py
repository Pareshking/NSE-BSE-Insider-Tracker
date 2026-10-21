"""Promoter-group members from the shareholding pattern (docs/TODO.md item 21):
the parser on real XBRLs (tests/fixtures/nse_events/shp_members/, fetched from
NSE's archive on 12 Oct 2026 and trimmed to the facts the parsers read, PAN
dropped), the clean table, the link to insider filings, and one decision-maker
per promoter group in clusters and breadth."""
from __future__ import annotations

import io
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from conftest import FIXTURES
from test_archive_and_writer import FakeR2
from test_nse_events import FakeNSE

from collectors.nse_events import parsers
from insiders_clean import promoter_group, signals

SHP = FIXTURES / 'nse_events' / 'shp_members'


def xml(name):
    return (SHP / f'{name}.xml').read_text(encoding='utf-8')


# --- parser --------------------------------------------------------------------

def test_members_add_up_to_the_promoter_total_on_each_filing():
    # taxonomy 2025-10-31 (Jun 2026) and 2025-05-31 (MOTILALOFS, Jun 2025)
    for name, n in (('ASIANPAINT_2026Q2', 117), ('ADANIENT_2026Q2', 21), ('COALINDIA_2026Q2', 1),
                    ('MOTILALOFS_2025Q2', 28)):
        members, check = parsers.parse_shp_members(xml(name))
        assert len(members) == n and check['check'] == 'match', name
        assert check['member_shares'] == parsers.parse_shp_xbrl(xml(name))['promoter_shares']


def test_member_rows_carry_name_section_shares_and_never_a_pan():
    members, _ = parsers.parse_shp_members(xml('ASIANPAINT_2026Q2'))
    first = members[0]
    assert first['member_name_filed'] == 'Dipika Amar Vakil' and first['sub_category'] == 'Individual or HUF'
    assert first['shares'] == 12761340 and first['pct_of_company'] == 1.33
    names = {m['member_name_filed'] for m in members}
    assert 'SBI Mutual Fund' not in names and 'Life Insurance Corporation of India' not in names  # public holders
    assert {'Trusts', 'Bodies Corporate', 'Non-resident or foreign individual'} <= {m['sub_category'] for m in members}
    assert not any('account' in k.lower() or v == '******' for m in members for k, v in m.items())
    adani, _ = parsers.parse_shp_members(xml('ADANIENT_2026Q2'))
    assert sum(m['sub_category'] == 'Overseas Corporate Bodies' for m in adani) == 10
    coal, _ = parsers.parse_shp_members(xml('COALINDIA_2026Q2'))
    assert coal[0]['sub_category'] == 'Central or state government'


def test_company_with_no_promoter_group_is_zero_as_filed_not_a_failure():
    facts = parsers.parse_shp_xbrl(xml('ITC_2026Q2'))
    assert facts['no_promoter_group'] and facts['promoter_shares'] == 0 and facts['promoter_holding_pct_xbrl'] == 0
    assert facts['promoter_pledge_pct'] is None          # nothing to pledge, not 0%
    members, check = parsers.parse_shp_members(xml('ITC_2026Q2'))
    assert members == [] and check['check'] == 'match'


def test_other_missing_promoter_figures_fail_with_their_reason():
    itc = xml('ITC_2026Q2')
    broken = itc.replace('contextRef="PublicShareholding_ContextI"', 'contextRef="Elsewhere"')
    with pytest.raises(ValueError, match='public shares do not make up the total'):
        parsers.parse_shp_xbrl(broken)
    with pytest.raises(ValueError, match='promoter context filed without a share count'):
        parsers.parse_shp_xbrl(itc + '<xbrli:context id="ShareholdingOfPromoterAndPromoterGroup_ContextI"/>')
    with pytest.raises(ValueError, match='total shares not found'):
        parsers.parse_shp_xbrl('<xbrl></xbrl>')


# --- clean table and link ---------------------------------------------------------

FILING = {'event_id': 'e1', 'record_id': '1', 'symbol': 'ASIANPAINT', 'isin': 'INE021A01026', 'company': 'Asian Paints',
          'quarter_end': '2026-06-30', 'submission_date': '2026-07-18', 'xbrl_url': 'u'}


def group():
    m, c = parsers.parse_shp_members(xml('ASIANPAINT_2026Q2'))
    return promoter_group.member_rows(m, FILING, c['check'], 'sha', '2026-10-12')


def test_clean_members_keeps_the_revised_filing_and_the_latest_parse():
    g = group()
    revised = g.head(3).assign(event_id='e2', submission_date='2026-07-25')
    reparsed = g.head(2).assign(parsed_on='2026-10-13')
    table, rep = promoter_group.clean_members([g, revised])
    assert set(table['event_id']) == {'e2'} and len(table) == 3 and rep['companies'] == 1
    table, _ = promoter_group.clean_members([g, reparsed])
    assert len(table) == 2                                  # the later parse of the same filing wins


def trade(name, role, isin='INE021A01026', side='BUY', day='2026-10-01', value=1e7):
    from insiders_clean.entities import entity_display, entity_key
    return {'isin': isin, 'nse_symbol': 'ASIANPAINT', 'company': 'Asian Paints', 'person_id': entity_key(name),
            'person_name': entity_display(name), 'person_role': role, 'side': side, 'is_token': False,
            'seen': pd.Timestamp(day), 'value': value, 'pct_of_mcap': 0.01}


def test_link_by_identity_only():
    t = pd.DataFrame([trade('DIPIKA AMAR VAKIL', 'promoter_group'),          # same key as filed
                      trade('Amar Arvind Vakil HUF', 'promoter_group'),        # pattern: '... HUF (VARUN AMAR VAKIL)'
                      trade('Dipika A Vakil', 'promoter_group'),               # a different spelling: not linked
                      trade('Amit Syngle', 'kmp'),
                      trade('Dipika Amar Vakil', 'promoter', isin='INE000X01010')])  # another company
    out, rep = promoter_group.link(t, group())
    assert out['promoter_group_id'].tolist() == ['group:INE021A01026', 'group:INE021A01026', None, None, None]
    assert out['promoter_group_key'].tolist()[:2] == ['name', 'name_before_bracket']
    assert out['promoter_group_quarter'].iloc[0] == '2026-06-30'
    p = rep['promoter_filings']
    assert (p['all'], p['company_has_list'], p['linked'], p['linked_by_name_before_bracket']) == (4, 3, 2, 1)
    assert p['unlinked_filers'] == 1 and p['unlinked_examples'] == ['ASIANPAINT: Dipika A Vakil']


def test_no_lists_links_nothing():
    out, rep = promoter_group.link(pd.DataFrame([trade('Dipika Amar Vakil', 'promoter')]), None)
    assert out['promoter_group_id'].isna().all() and rep['lists'] == 0


# --- one decision-maker per promoter group ------------------------------------------

def linked(rows):
    return promoter_group.link(pd.DataFrame(rows), group())[0]


def test_promoter_group_buying_together_is_one_decision_maker_not_a_cluster():
    # Vakil, Choksi and Dani are three surnames: two families or more by the old rule, one group by the pattern.
    rows = [trade('Dipika Amar Vakil', 'promoter_group'), trade('Prafullika Shailesh Choksi', 'promoter_group'),
            trade('Malav A Dani', 'promoter_group')]
    ref = pd.Timestamp('2026-10-05')
    assert signals.clusters(pd.DataFrame(rows), ref).empty               # filed as promoter group: one decision-maker even without the pattern (audit D1)
    assert signals.clusters(linked(rows), ref).empty                     # with it: one decision-maker
    assert signals.insider_details(linked(rows), ref).iloc[0] == '3 promoter-group members · 1 decision-maker · 3 trades'


def test_group_and_a_director_are_two_decision_makers():
    rows = [trade('Dipika Amar Vakil', 'promoter_group'), trade('Malav A Dani', 'promoter_group'),
            trade('Amit Syngle', 'director')]
    c = signals.clusters(linked(rows), pd.Timestamp('2026-10-05')).iloc[0]
    assert (c['buyers'], c['decision_makers'], c['group_buyers']) == (3, 2, 2)
    assert c['who'] == '3 buyers, 2 decision-makers: promoter group (2), director'


def test_a_link_never_makes_a_cluster_easier():
    # An unlinked spelling with the same surname as a linked member stays in that family.
    rows = [trade('Dipika Amar Vakil', 'promoter_group'), trade('Dipika A Vakil', 'promoter_group')]
    ref = pd.Timestamp('2026-10-05')
    assert signals.clusters(pd.DataFrame(rows), ref).empty and signals.clusters(linked(rows), ref).empty


def test_breadth_counts_the_group_once():
    rows = [trade('Dipika Amar Vakil', 'promoter_group'), trade('Malav A Dani', 'promoter_group'),
            trade('Amit Syngle', 'kmp')]
    t = linked(rows).assign(signed_value=1e7, market_cap=1e12, trade_date_to=pd.Timestamp('2026-09-30'))
    b = signals.company_board(t, None, None, pd.Timestamp('2026-10-05')).iloc[0]
    assert (b['insiders'], b['decision_makers']) == (3, 2)


# --- nightly collection --------------------------------------------------------------

def test_nightly_writes_a_write_once_batch_and_the_clean_member_table(monkeypatch):
    import clean_writer

    from collectors.nse_events import run_daily

    class Resp:
        status_code = 200

        def __init__(self, path):
            self.content = path.read_bytes()

    monkeypatch.setattr(clean_writer.requests, 'get', lambda url, **kw: Resp(
        FIXTURES / ('nse_sme_sample.csv' if 'SME' in url else 'nse_equity_sample.csv')))
    r2 = FakeR2()
    now = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)
    rep = run_daily.run(r2, FakeNSE(), date(2026, 10, 7), 10, streams=('shareholding',), now=now)
    batches = [k for k in r2.objects if k.startswith('archive/nse_events/promoter_group/')]
    assert batches == ['archive/nse_events/promoter_group/batch=2026-10-07T160000.parquet']
    g = pd.read_parquet(io.BytesIO(r2.objects['clean/current/promoter_group.parquet']))
    assert g['event_id'].nunique() == 5 and (g['members_check'] == 'match').all()   # ZEEL's XBRL for each
    assert 'Subhash Chandra' in set(g['member_name_filed'])
    cov = rep['streams']['shareholding']['coverage']
    assert cov['members_status_latest'] == {'ok': 5} and cov['pending_members'] == 0
    # the next night: nothing re-fetched, no new batch
    rep2 = run_daily.run(r2, FakeNSE(), date(2026, 10, 8), 10, streams=('shareholding',),
                         now=datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc))
    assert rep2['xbrl_fetched'] == 0 and 'batch_written' not in rep2['promoter_group']


def test_xbrl_is_kept_gzip_compressed_and_write_once():
    import gzip

    from test_raw_store import OnceR2

    from collectors.nse_events.run_daily import fetch_xbrl
    from insiders_clean.raw_store import RawStore
    r2 = OnceR2()
    ticks = iter(datetime(2026, 10, 7, 16, i, tzinfo=timezone.utc) for i in range(10))
    raw = RawStore(r2, bucket='b', collector='test', clock=lambda: next(ticks))
    listing = pd.DataFrame({'event_id': ['a', 'b'], 'symbol': ['ZEEL', 'X'], 'record_id': ['1', '2'],
                            'xbrl_url': ['u1', 'u2'], 'quarter_end': pd.to_datetime(['2026-06-30'] * 2)})
    fetch_xbrl(FakeNSE(), listing, None, {'notes': []}, raw=raw)        # the same XBRL bytes for both rows
    blobs = [k for k in r2.objects if '/blobs/' in k]
    assert len(blobs) == 1 and blobs[0].startswith('raw_v2/nse/shareholding_xbrl/blobs/') and blobs[0].endswith('.gz')
    assert gzip.decompress(r2.objects[blobs[0]]).decode('utf-8') == FakeNSE().xml
    assert sum('/fetches/' in k for k in r2.objects) == 2


def test_filings_parsed_before_member_lists_are_fetched_again_only_when_latest():
    from collectors.nse_events.run_daily import fetch_xbrl
    listing = pd.DataFrame({'event_id': ['old', 'new'], 'symbol': ['ZEEL', 'ZEEL'], 'xbrl_url': ['u1', 'u2'],
                            'quarter_end': pd.to_datetime(['2026-03-31', '2026-06-30']),
                            'submission_date': pd.to_datetime(['2026-04-20', '2026-07-20'])})
    # parsed, investor types in, no members yet
    known = listing.assign(xbrl_status='ok', promoter_shares=1.0, total_shares=2.0, categories_status='ok')
    members, nse = [], FakeNSE()
    out = fetch_xbrl(nse, listing, known, {'notes': []}, members=members).set_index('event_id')
    assert nse.calls == 1 and len(members) == 1 and set(members[0]['event_id']) == {'new'}
    assert out.loc['new', 'members_status'] == 'ok' and out.loc['new', 'promoter_shares'] == 1.0  # totals kept
    assert pd.isna(out.loc['old', 'members_status'])


def test_coverage_counts_no_promoter_group_and_failure_reasons():
    from collectors.nse_events.run_daily import shareholding_coverage
    df = pd.DataFrame({
        'symbol': ['A', 'B', 'C'], 'quarter_end': pd.to_datetime(['2026-06-30'] * 3),
        'xbrl_status': ['ok', 'ok', 'failed: ValueError'], 'promoter_pledge_pct': [None, 1.0, None],
        'no_promoter_group': [True, False, None], 'xbrl_error': [None, None, 'total shares not found'],
        'members_status': ['ok', 'pending', None]})
    c = shareholding_coverage(df)
    assert c['no_promoter_group'] == 1 and c['xbrl_failure_reasons'] == {'total shares not found': 1}
    assert c['pending_members'] == 2 and c['members_status_latest'] == {'ok': 1, 'pending': 1, 'not fetched': 1}


def test_pipeline_links_real_filings_to_the_real_member_list(real_nse_rows):
    # ZEEL, 07 Oct 2026: 'Sunbright Mauritius\nInvestments Limited' (promoter group) is named in ZEEL's Jun 2026 pattern.
    from conftest import BSE_ROWS, ROOT, RUN_DATE, canonical

    from insiders_clean.calendar import seed_state
    from insiders_clean.pipeline import run
    m, c = parsers.parse_shp_members((FIXTURES / 'nse_events' / 'shp_ZEEL_2026Q2.xml').read_text(encoding='utf-8'))
    zeel = promoter_group.member_rows(m, {**FILING, 'symbol': 'ZEEL', 'isin': 'INE256A01028'}, c['check'], None, RUN_DATE)
    vr = pd.read_csv(ROOT / 'reference_data' / 'security_master_20260901.csv', dtype=str, keep_default_na=False)
    tables, rep = run({('nse', 'insider_trading'): canonical('nse', 'insider_trading', real_nse_rows)}, RUN_DATE,
                      seed_state(), vr_master=vr, nse_lists=[pd.read_csv(FIXTURES / 'nse_equity_sample.csv', dtype=str)],
                      market_cap_rows=BSE_ROWS, promoter_group=zeel)
    t = tables['insider_trades']
    z = t[(t['nse_symbol'] == 'ZEEL') & t['person_role'].isin(['promoter', 'promoter_group'])]
    assert len(z) and (z['promoter_group_id'] == 'group:INE256A01028').all()
    assert t.loc[t['nse_symbol'] != 'ZEEL', 'promoter_group_id'].isna().all()
    link = rep['promoter_group_link']
    assert link['lists'] == 1 and link['promoter_filings']['linked'] == len(z)
