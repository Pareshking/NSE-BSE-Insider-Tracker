"""Public shareholders over 1% from the shareholding pattern (Tables III and IV): the parser on real XBRLs
(tests/fixtures/nse_events/shp_public/, whole files fetched from NSE's archive on 19 Nov 2026, gzip-compressed,
PAN masked by NSE as filed; shp_members/ are trimmed copies), the holder key, the clean table, the change since the
last quarter, the nightly batch and the catch-up from the kept raw XBRLs, and the two page uses."""
from __future__ import annotations

import gzip
import io
import re
import sys
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from conftest import FIXTURES, ROOT
from test_archive_and_writer import FakeR2
from test_nse_events import FakeNSE

from collectors.nse_events import parsers
from insiders_clean import public_holders as ph

EV = FIXTURES / 'nse_events'
PUB = EV / 'shp_public'
WHOLE = sorted(PUB.glob('*.xml.gz')) + [EV / 'shp_ZEEL_2026Q2.xml']


def text(path):
    return gzip.decompress(path.read_bytes()).decode('utf-8') if path.suffix == '.gz' else path.read_text(encoding='utf-8')


def pub(name):
    return text(PUB / f'{name}.xml.gz')


def rows(name):
    return {r['holder_name_filed']: r for r in parsers.parse_shp_public_holders(pub(name))[0]}


# --- parser ----------------------------------------------------------------------

def test_itc_sbi_mutual_funds_as_filed():
    for xml in (pub('ITC_2026Q2'), (EV / 'shp_members' / 'ITC_2026Q2.xml').read_text(encoding='utf-8')):
        sbi = {r['holder_name_filed']: r for r in parsers.parse_shp_public_holders(xml)[0]}['SBI Mutual Funds']
        assert sbi['shares'] == 421150103 and round(sbi['pct_of_company'], 2) == 3.36   # filed 0.0336
        assert (sbi['type'], sbi['category'], sbi['section']) == ('mf', 'MutualFundsOrUTI', 'MutualFundsOrUTI')


def test_itc_fpi_and_insurer_rows():
    r = rows('ITC_2026Q2')
    gs = r['Goldman Sachs Trust II - Goldman Sachs GQG Partners International Opportunities Fund']
    assert gs['type'] == 'fpi' and gs['shares'] == 257540712 and round(gs['pct_of_company'], 2) == 2.06
    assert gs['category'] == 'InstitutionsForeignPortfolioInvestorCategoryOne'
    lic = r['Life Insurance Corporation of India']
    assert lic['type'] == 'insurance' and lic['shares'] == 2041625642 and round(lic['pct_of_company'], 2) == 16.30
    assert r['Tobacco Manufacturers (India) Limited']['type'] == 'other_foreign'          # FDI, B2a
    assert r['Specified Undertaking of the Unit Trust of India']['type'] == 'banks_fi'    # B1j


@pytest.mark.parametrize('path', WHOLE, ids=lambda p: p.name.split('.')[0])
def test_named_holders_never_exceed_their_category_total(path):
    xml = text(path)
    found, check = parsers.parse_shp_public_holders(xml)
    assert found and check['check'] == 'ok' and not check['unmapped']
    filed = {c: float(v) for c, v in re.findall(r'<in-bse-shp:NumberOfShares\b[^>]*?contextRef="(\w+?)_ContextI"[^>]*>([^<]*)<', xml)}
    cats = parsers.parse_shp_categories(xml)
    for key, total in (('category', lambda c: filed.get(c, 0.0)), ('type', lambda t: cats[f'{t}_shares'])):
        for value in {r[key] for r in found}:
            assert sum(r['shares'] for r in found if r[key] == value) <= total(value) + 0.5, (key, value)
    assert all(r['pct_of_company'] == round(r['shares'] / cats['pct_base_shares'] * 100, 4) for r in found)


def test_sub_category_totals_typed_as_names_are_not_holders():
    found, check = parsers.parse_shp_public_holders(pub('ITC_2026Q3'))
    names = {r['holder_name_filed'] for r in found}
    assert check['category_rows'] == 3
    assert not names & {'Foreign Institutional Investors', 'QIB - Insurance Company Registered', 'Insurance Funds- Dept of Post India'}


def test_table_iv_and_the_other_sections_carry_names():
    a = rows('AAATECH_2026Q3')
    assert a['Amay Vatsalya']['type'] == 'hni' and a['Amay Vatsalya']['shares'] == 212583
    assert a['L7 Hitech Private Limited']['type'] == 'corporate'
    assert a['Nautilus Private Capital Ltd']['category'] == 'InstitutionsForeignPortfolioInvestorCategoryTwo'
    ar = rows('ARIS_2026Q3')
    mo = ar['Motilal Oswal Financial  Services Limited - Proprietary Account']
    assert (mo['type'], mo['sub_category']) == ('other_public', 'Clearing Members')       # B4m, "more than 1%"
    assert ar['Neomile Growth Fund - Series I']['type'] == 'aif'
    assert ar['Pradip Jethalal Morbia']['category'] == 'NonResidentIndians'
    assert rows('AADHARHFC_2026Q3')['ICICI BANK LTD']['type'] == 'banks_fi'
    assert rows('MOMSBELIEF_2026Q3')['LRSD SECURITIES PVT LTD']['category'] == 'NBFCsRegisteredWithRBI'
    adr = rows('ICICIBANK_2026Q3')['DEUTSCHE BANK TRUST COMPANY AMERICAS']
    assert (adr['type'], adr['category'], adr['pct_of_company']) == ('other_foreign', 'OverseasDepositories', 15.755)
    assert rows('IDEA_2026Q3')['Department of Investment and Public Asset Management']['type'] == 'govt'
    assert rows('GSPLTRANS_2026Q3')['GUJARAT INDUSTRIAL DEVELOPMENT CORPORATION']['type'] == 'govt'    # B3c
    trust = [r for n, r in rows('HEALTHX_2026Q3').items() if 'Employees Trust' in n][0]
    assert trust['category'].startswith('TrustsWhereAnyPerson')                                       # B4e


def test_promoter_members_and_non_public_holders_are_left_out():
    names = {r['holder_name_filed'] for r in parsers.parse_shp_public_holders(
        (EV / 'shp_members' / 'ASIANPAINT_2026Q2.xml').read_text(encoding='utf-8'))[0]}
    assert names == {'SBI Mutual Fund', 'ICICI Prudential Mutual Fund', 'Life Insurance Corporation of India'}
    eternal = rows('ETERNAL_2026Q3')
    assert 'Foodie Bay Employees Esop Trust' not in eternal          # employee benefit trust: Table IV C, not public
    assert eternal['Info Edge (India) Limited']['type'] == 'corporate'


def test_a_section_not_read_is_reported_never_typed():
    xml = pub('ITC_2026Q3').replace('D_MutualFundsOrUTI_Context15', 'D_DetailsOfSharesHeldBySomethingNew_Context15')
    found, check = parsers.parse_shp_public_holders(xml)
    assert check['check'] == 'unmapped' and check['unmapped'] == {'DetailsOfSharesHeldBySomethingNew': 1}
    assert 'SBI Mutual Funds' not in {r['holder_name_filed'] for r in found}


def test_old_taxonomy_percent_is_computed_from_shares():
    # taxonomy 2025-05-31 files 5.09 (a percentage), 2025-10-31 0.0336 (a fraction): both read from the shares
    navin = {r['holder_name_filed']: r for r in parsers.parse_shp_public_holders(
        (EV / 'shp_members' / 'MOTILALOFS_2025Q2.xml').read_text(encoding='utf-8'))[0]}['Navin Agarwal']
    assert navin['type'] == 'other_public' and round(navin['pct_of_company'], 2) == 5.09


# --- holder key, clean table, changes -----------------------------------------------

def test_holder_key_merges_spellings_and_keeps_accounts_apart():
    k = ph.holder_key
    assert k('SBI Mutual Funds') == k('SBI MUTUAL FUND') == k('Sbi Mutual Fund.') == 'sbi-mutual-fund'
    assert k('The New India Assurance Company Limited') == k('New India Assurance Co. Ltd')
    assert k('L7 Hitech Private Limited') == k('L7 HITECH PVT LTD') == 'l7-hitech'
    assert k('Nps Trust- A/C Sbi Pension Fund Scheme') == k('NPS TRUST - A/c. SBI PENSION FUND SCHEME')
    assert k('Nps Trust- A/C Sbi Pension Fund Scheme') != k('Nps Trust')
    assert k('Procter &amp; Gamble') == k('Procter and Gamble') and k(None) is None and k('  ') is None


def filing(eid, sym, q, sub, isin='INE154A01025'):
    return {'event_id': eid, 'record_id': eid, 'symbol': sym, 'isin': isin, 'company': sym, 'quarter_end': q,
            'submission_date': sub, 'xbrl_url': f'u{eid}'}


def table_of(*parts):
    batches = [ph.holder_rows(parsers.parse_shp_public_holders(x)[0], f, 'ok', 'sha', run) for x, f, run in parts]
    return ph.clean_holders(batches)


def test_clean_table_keeps_the_latest_parse_and_the_revised_filing():
    q3 = pub('ITC_2026Q3')
    t, rep = table_of((pub('ITC_2026Q2'), filing('a', 'ITC', '2026-06-30', '2026-07-15'), '2026-07-16'),
                      (q3, filing('b', 'ITC', '2026-09-30', '2026-10-14'), '2026-10-15'),
                      (q3, filing('b', 'ITC', '2026-09-30', '2026-10-14'), '2026-11-19'),        # parsed again
                      (q3.replace('430729416', '430729417'), filing('c', 'ITC', '2026-09-30', '2026-10-20'), '2026-10-21'))  # revised
    assert list(t.columns) == ph.HOLDER_COLUMNS and rep['filings'] == 2 and rep['companies'] == 1
    assert set(t['event_id']) == {'a', 'c'}
    sbi = t[(t['holder_key'] == 'sbi-mutual-fund') & (t['event_id'] == 'c')].iloc[0]
    assert sbi['shares'] == 430729417 and sbi['holder_name'] == 'SBI Mutual Funds' and sbi['type'] == 'mf'


def test_changes_since_last_quarter_on_itc():
    t, _ = table_of((pub('ITC_2026Q2'), filing('a', 'ITC', '2026-06-30', '2026-07-15'), 'r'),
                    (pub('ITC_2026Q3'), filing('b', 'ITC', '2026-09-30', '2026-10-14'), 'r'),
                    (pub('IDEA_2026Q3'), filing('i', 'IDEA', '2026-09-30', '2026-10-20', 'INE669E01016'), 'r'))
    ch = ph.changes(t).set_index(['isin', 'holder_key'])
    itc = ch.loc['INE154A01025']
    sbi = itc.loc['sbi-mutual-fund']
    assert sbi['change'] == 'added' and sbi['shares_change'] == 430729416 - 421150103
    assert sbi['pct_change'] == round(3.4383 - 3.3621, 4)
    gqg = itc.loc['gqg-partners-emerging-markets-equity-fund']
    assert gqg['change'] == 'exited' and pd.isna(gqg['shares']) and gqg['pct_change'] == -1.057
    assert itc.loc['goldman-sachs-trust-ii-goldman-sachs-gqg-partners-international-opportunities-fund', 'change'] == 'cut'
    assert itc.loc['tobacco-manufacturers-india', 'change'] == 'same'
    assert itc['change'].iloc[-1] == 'exited'                                  # left the list: shown last
    assert set(ch.loc['INE669E01016', 'change']) == {'no_previous'}            # one quarter: nothing compared, not "new"
    one = t[~((t['holder_key'] == 'sbi-mutual-fund') & (t['event_id'] == 'a'))]
    assert ph.changes(one).set_index('holder_key').loc['sbi-mutual-fund', 'change'] == 'new'


def test_holdings_of_a_holder_across_companies():
    t, _ = table_of((pub('ITC_2026Q3'), filing('b', 'ITC', '2026-09-30', '2026-10-14'), 'r'),
                    (pub('ICICIBANK_2026Q3'), filing('c', 'ICICIBANK', '2026-09-30', '2026-10-18', 'INE090A01021'), 'r'))
    h = ph.holdings_of(t, {'sbi-mutual-fund'})
    assert list(h['symbol']) == ['ICICIBANK', 'ITC'] and list(h['pct_of_company']) == [6.2224, 3.4383]
    assert ph.holdings_of(t, {'nobody'}).empty and ph.holdings_of(t, {None}).empty


# --- nightly batch and catch-up --------------------------------------------------------

@pytest.fixture()
def master(monkeypatch):
    import clean_writer

    class Resp:
        status_code = 200

        def __init__(self, path):
            self.content = path.read_bytes()

    monkeypatch.setattr(clean_writer.requests, 'get', lambda url, **kw: Resp(
        FIXTURES / ('nse_sme_sample.csv' if 'SME' in url else 'nse_equity_sample.csv')))


def test_nightly_writes_a_write_once_batch_and_the_clean_table(master):
    from collectors.nse_events import run_daily
    r2 = FakeR2()
    rep = run_daily.run(r2, FakeNSE(), date(2026, 10, 7), 10, streams=('shareholding',),
                        now=datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc))
    assert [k for k in r2.objects if k.startswith('archive/nse_events/public_holders/')] == \
        ['archive/nse_events/public_holders/batch=2026-10-07T160000.parquet']
    t = pd.read_parquet(io.BytesIO(r2.objects['clean/current/public_holders.parquet']))
    assert t['event_id'].nunique() == 5 and 'government-pension-fund-global' in set(t['holder_key'])   # ZEEL's XBRL
    assert rep['public_holders']['holders'] == len(t) and rep['public_holders_parse'] == {'ok': 5}
    rep2 = run_daily.run(r2, FakeNSE(), date(2026, 10, 8), 10, streams=('shareholding',),
                         now=datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc))
    assert rep2['xbrl_fetched'] == 0 and 'batch_written' not in rep2['public_holders']   # nothing fetched, no batch


def test_catch_up_reads_the_kept_raw_xbrls_with_no_nse_call(master):
    from test_raw_store import OnceR2

    from collectors.nse_events import run_daily
    from insiders_clean.raw_store import RawStore
    r2 = OnceR2()
    raw = RawStore(r2, bucket='b', collector='test', clock=lambda: datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc))
    arch = pd.DataFrame({'event_id': ['e1', 'e2', 'e3'], 'record_id': ['211231', '214129', '9'],
                         'symbol': ['ITC', 'ITC', 'XYZ'], 'isin': ['INE154A01025', 'INE154A01025', None],
                         'company': ['ITC Limited'] * 2 + ['X'], 'quarter_end': ['2026-06-30', '2026-09-30', '2026-06-30'],
                         'submission_date': ['2026-07-15', '2026-10-14', '2026-07-20'], 'xbrl_url': ['u1', 'u2', 'u3'],
                         'xbrl_status': ['ok'] * 3, 'first_seen': ['2026-10-14'] * 3, 'last_seen': ['2026-10-15'] * 3})
    for i, name in ((0, 'ITC_2026Q2'), (1, 'ITC_2026Q3')):
        run_daily._keep_raw(raw, pub(name), arch.iloc[i])
    buf = io.BytesIO()
    arch.to_parquet(buf, index=False)
    r2.objects['archive/nse_events/shareholding/year=2026.parquet'] = buf.getvalue()
    nse = FakeNSE()
    rep = run_daily.run(r2, nse, date(2026, 11, 19), 10, streams=('shareholding',), reparse_raw=True,
                        now=datetime(2026, 11, 19, 16, 0, tzinfo=timezone.utc))
    assert nse.calls == 0 and rep['shareholding_reparse']['public_holders_parse'] == {'ok': 2}
    t = pd.read_parquet(io.BytesIO(r2.objects['clean/current/public_holders.parquet']))
    assert set(t['event_id']) == {'e1', 'e2'} and len(t) == 15 + 14             # XYZ has no raw copy: not read
    assert ph.changes(t).set_index('holder_key').loc['sbi-mutual-fund', 'change'] == 'added'


# --- site ---------------------------------------------------------------------------------

def site():
    for p in (str(ROOT / 'streamlit_app'), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def test_company_section_rows_name_the_holder_and_the_change():
    site()
    from screens import company
    t, _ = table_of((pub('ITC_2026Q2'), filing('a', 'ITC', '2026-06-30', '2026-07-15'), 'r'),
                    (pub('ITC_2026Q3'), filing('b', 'ITC', '2026-09-30', '2026-10-14'), 'r'))
    out = company.holder_rows(ph.changes(t))
    first, last = out[0], out[-1]
    assert 'Tobacco Manufacturers' in first['h'] and '/entity?id=tobacco-manufacturers-india' in first['h']
    assert first['p'] == '17.79%' and first['c'] == 'Unchanged' and first['t'] == 'Foreign direct or other foreign institution'
    sbi = next(r for r in out if 'SBI Mutual Funds' in r['h'])
    assert sbi['c'] == 'Added 95,79,313 shares, +0.08 pts'
    assert 'GQG Partners Emerging' in last['h'] and last['p'] == '—' and last['c'].startswith('Left the list (was 1.06%)')


def test_store_keeps_the_last_two_quarters_and_the_page_columns():
    site()
    from data import store
    df = pd.DataFrame({'symbol': ['ITC'] * 3 + ['abc', 'ABC'], 'holder_key': list('abcde'),
                       'quarter_end': pd.to_datetime(['2026-03-31', '2026-06-30', '2026-09-30', '2026-06-30', '2026-06-30'])})
    cut = store._latest_only(df, 'symbol', 'quarter_end', n=store.LATEST_N['public_holders'])
    assert list(cut['holder_key']) == ['b', 'c', 'd', 'e']
    assert 'public_holders' in store.TABLES and 'holder_key' in store.ONLY['public_holders']
    assert 'xbrl_url' not in store.ONLY['public_holders'] and 'holder_name_filed' not in store.ONLY['public_holders']


def test_entity_page_finds_a_holder_by_its_key_or_its_name():
    site()
    from screens import entity
    t, _ = table_of((pub('ITC_2026Q3'), filing('b', 'ITC', '2026-09-30', '2026-10-14'), 'r'),
                    (pub('ICICIBANK_2026Q3'), filing('c', 'ICICIBANK', '2026-09-30', '2026-10-18', 'INE090A01021'), 'r'))
    sec = pd.DataFrame({'isin': ['INE154A01025'], 'display_name': ['ITC']})
    by_id = entity.holdings(t, 'sbi-mutual-fund', None, sec)
    by_name = entity.holdings(t, 'some-other-id', 'SBI MUTUAL FUND', sec)
    assert list(by_id['symbol']) == list(by_name['symbol']) == ['ICICIBANK', 'ITC']
    assert list(by_id['company']) == ['ICICIBANK', 'ITC'] and by_id['type_label'].iloc[0] == 'Mutual fund'
    assert by_id['since'].iloc[0] == '—'                       # one quarter only: no change shown
    assert entity.holdings(t, 'nobody', 'Nobody At All', sec).empty
