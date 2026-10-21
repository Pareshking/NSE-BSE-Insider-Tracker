"""Ownership by investor type from the shareholding pattern (Tables III and IV):
the parser on real XBRLs (tests/fixtures/nse_events/shp_categories/, fetched
from NSE's archive on 21 Oct 2026 and trimmed to the category-level facts;
shp_ZEEL_2026Q2.xml is a whole file), the fetch path, and the re-parse of the
kept raw XBRLs with no NSE call."""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from conftest import FIXTURES
from test_archive_and_writer import FakeR2
from test_nse_events import FakeNSE

from collectors.nse_events import parsers

EV = FIXTURES / 'nse_events'
CAT = EV / 'shp_categories'
REAL = sorted(CAT.glob('*.xml')) + [EV / 'shp_ZEEL_2026Q2.xml']


def xml(name):
    return (CAT / f'{name}.xml').read_text(encoding='utf-8')


def filed(text, tag):
    return {c: float(v) for c, v in
            re.findall(rf'<in-bse-shp:{tag} contextRef="(\w+?)_ContextI"[^>]*>([^<]*)<', text)}


# --- parser ----------------------------------------------------------------------

@pytest.mark.parametrize('path', REAL, ids=lambda p: p.stem)
def test_categories_add_up_to_the_total_on_each_real_filing(path):
    text = path.read_text(encoding='utf-8')
    c = parsers.parse_shp_categories(text)
    assert c['categories_check'] == 'match' and c['categories_unmapped'] is None
    shares = sum(c[f'{b}_shares'] for b in parsers.SHP_CATEGORIES) + c['dr_shares']
    assert shares == parsers.parse_shp_xbrl(text)['total_shares']
    assert sum(c[f'{b}_pct'] for b in parsers.SHP_CATEGORIES) == pytest.approx(100, abs=0.001)


@pytest.mark.parametrize('path', REAL, ids=lambda p: p.stem)
def test_percentages_are_the_filings_own(path):
    # Each company's own % column (4 decimals of a fraction; taxonomy 2025-05-31 files it in percent).
    text = path.read_text(encoding='utf-8')
    c = parsers.parse_shp_categories(text)
    pct = filed(text, 'ShareholdingAsAPercentageOfTotalNumberOfShares')
    scale = 1 if pct['ShareholdingPattern'] > 1 else 100
    pairs = {'mf': 'MutualFundsOrUTI', 'insurance': 'InsuranceCompanies', 'aif': 'AlternativeInvestmentFunds',
             'retail': 'ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh',
             'hni': 'ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh',
             'corporate': 'BodiesCorporate', 'promoter': 'ShareholdingOfPromoterAndPromoterGroup'}
    for bucket, ctx in pairs.items():
        if ctx in pct:
            assert c[f'{bucket}_pct'] == pytest.approx(pct[ctx] * scale, abs=0.0051), bucket


def test_sbin_sep_2026_checked_by_hand():
    # SBIN, quarter ended 30 Sep 2026 (record 214335, filed 14 Oct 2026). Total 9,230,766,786 shares, of which
    # 70,396,990 are held by the custodian against GDRs (Table IV C1): the % base is 9,160,369,796, as SEBI's form
    # computes it. NSE's listing: promoter 55.45, public 44.55, employee trusts 0.
    c = parsers.parse_shp_categories(xml('SBIN_2026Q3'))
    assert c['dr_shares'] == 70_396_990 and c['pct_base_shares'] == 9_160_369_796
    assert c['promoter_pct'] == 55.4538                                # 5,079,775,288 (President of India)
    assert (c['mf_shares'], c['mf_pct']) == (1_252_853_591, 13.6769)   # filed 0.1368
    assert (c['insurance_shares'], c['insurance_pct']) == (904_140_881, 9.8701)
    assert c['banks_fi_shares'] == 779_486 + 132_686 + 1_280_678       # banks + NBFCs + other financial institutions
    assert c['other_dii_shares'] == 208_802_886 + 11_511_216           # provident / pension funds + domestic SWF
    assert c['aif_shares'] == 33_418_025
    assert (c['fpi_shares'], c['fpi_pct']) == (988_441_904 + 25_237_951, 11.0659)   # category I + II
    assert c['other_foreign_shares'] == 312_200
    assert c['govt_shares'] == 19_000 + 1_219_580 + 234_473             # central + state + govt-promoted companies
    assert (c['retail_shares'], c['retail_pct']) == (516_963_050, 5.6435)
    assert (c['hni_shares'], c['hni_pct']) == (16_727_765, 0.1826)
    assert c['corporate_shares'] == 56_494_515
    # associates, directors, KMP, IEPF, NRIs, foreign nationals, foreign companies, any other
    assert c['other_public_shares'] == 35 + 1_590 + 140 + 16_227_246 + 27_760_696 + 2_120 + 1_698_641 + 16_334_153
    assert c['non_public_other_shares'] == 0 and c['promoter_pct'] + c['non_public_other_pct'] == pytest.approx(
        100 - 44.55, abs=0.005)


def test_depository_receipts_sit_outside_the_base_and_trusts_inside():
    hdfc = parsers.parse_shp_categories(xml('HDFCBANK_2026Q3'))     # ADRs, no promoter group
    assert hdfc['dr_shares'] == 2_051_218_867 and hdfc['promoter_shares'] == 0
    # the employee trust (C2) stays in the base: 0.0009% here, NSE's listing rounds it to 0
    assert hdfc['non_public_other_pct'] == 0.0009 and hdfc['dr_shares'] / hdfc['pct_base_shares'] > 0.15
    lt = parsers.parse_shp_categories(xml('LT_2026Q3'))             # no promoter group; employee trust in "any other"
    assert lt['promoter_pct'] == 0 and lt['other_public_pct'] > 10
    icici = parsers.parse_shp_categories(xml('ICICIBANK_2026Q3'))  # ICICI files its ADRs in public B2(f)
    assert icici['dr_shares'] == 0 and icici['other_foreign_pct'] > 10


def test_what_does_not_map_is_reported_never_put_in_a_bucket():
    text = xml('TDPOWERSYS_2026Q3')
    base = parsers.parse_shp_categories(text)
    # a public sub-category missing from the file: the subtotal no longer adds up
    gone = re.sub(r'<in-bse-shp:NumberOfShares contextRef="MutualFundsOrUTI_ContextI"[^>]*>[^<]*</in-bse-shp:NumberOfShares>',
                  '', text)
    c = parsers.parse_shp_categories(gone)
    assert c['categories_check'] == 'mismatch' and c['mf_shares'] == 0
    assert f'InstitutionsDomestic: {base["mf_shares"]:.0f} shares in no filed sub-category' in c['categories_unmapped']
    assert c['other_dii_shares'] == base['other_dii_shares']        # never filled by difference
    # a category this parser does not know: named, with its shares, and kept out of every bucket
    odd = text.replace('</xbrli:xbrl>', '<in-bse-shp:NumberOfShares contextRef="SomethingNew_ContextI" '
                                        'decimals="INF" unitRef="shares">5</in-bse-shp:NumberOfShares></xbrli:xbrl>')
    c = parsers.parse_shp_categories(odd)
    assert c['categories_unmapped'] == 'unknown category SomethingNew: 5 shares'
    assert c['categories_check'] == 'match' and c['mf_shares'] == base['mf_shares']
    with pytest.raises(ValueError):
        parsers.parse_shp_categories('<xbrl></xbrl>')


# --- fetch path ------------------------------------------------------------------

def test_filing_parsed_before_investor_types_is_fetched_once_more_for_them():
    from collectors.nse_events.run_daily import fetch_xbrl
    listing = pd.DataFrame({'event_id': ['old', 'new'], 'symbol': ['ZEEL', 'ZEEL'], 'xbrl_url': ['u1', 'u2'],
                            'quarter_end': pd.to_datetime(['2026-03-31', '2026-06-30']),
                            'submission_date': pd.to_datetime(['2026-04-20', '2026-07-20'])})
    known = listing.assign(xbrl_status='ok', promoter_shares=1.0, total_shares=2.0, members_status='ok',
                           members_check='match', categories_status=['ok', None], mf_pct=[9.0, None])
    members, nse = [], FakeNSE()
    out = fetch_xbrl(nse, listing, known, {'notes': []}, members=members).set_index('event_id')
    assert nse.calls == 1 and members == []                       # the member list is not parsed again
    assert out.loc['new', 'categories_status'] == 'ok' and round(out.loc['new', 'mf_pct'], 2) == 3.16
    assert out.loc['new', 'promoter_shares'] == 1.0 and out.loc['new', 'members_status'] == 'ok'  # kept
    assert out.loc['old', 'mf_pct'] == 9.0                         # carried from the archive, not fetched


def test_cap_leaves_investor_types_pending_without_touching_parsed_members():
    from collectors.nse_events.run_daily import fetch_xbrl
    listing = pd.DataFrame({'event_id': ['a'], 'symbol': ['ZEEL'], 'xbrl_url': ['u1'],
                            'quarter_end': pd.to_datetime(['2026-06-30'])})
    known = listing.assign(xbrl_status='ok', members_status='ok')
    out = fetch_xbrl(FakeNSE(), listing, known, {'notes': []}, max_xbrl=0).set_index('event_id')
    assert out.loc['a', 'categories_status'] == 'pending' and out.loc['a', 'members_status'] == 'ok'


# --- re-parse of the kept raw XBRLs -------------------------------------------------

@pytest.fixture()
def stored(monkeypatch):
    """An archive of three filings parsed before investor types existed; two have a raw copy."""
    import clean_writer
    from test_raw_store import OnceR2

    from collectors.nse_events import run_daily
    from insiders_clean.raw_store import RawStore

    class Resp:
        status_code = 200

        def __init__(self, path):
            self.content = path.read_bytes()

    monkeypatch.setattr(clean_writer.requests, 'get', lambda url, **kw: Resp(
        FIXTURES / ('nse_sme_sample.csv' if 'SME' in url else 'nse_equity_sample.csv')))
    r2 = OnceR2()
    raw = RawStore(r2, bucket='b', collector='test', clock=lambda: datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc))
    rows = pd.DataFrame({'event_id': ['e1', 'e2', 'e3'], 'record_id': ['214335', '200001', '9'],
                         'symbol': ['SBIN', 'ZEEL', 'XYZ'], 'isin': ['INE062A01020', 'INE256A01028', None],
                         'company': ['State Bank of India', 'Zee Entertainment', 'X'],
                         'quarter_end': ['2026-09-30', '2026-06-30', '2026-06-30'],
                         'submission_date': ['2026-10-14', '2026-07-20', '2026-07-20'],
                         'xbrl_url': ['u1', 'u2', 'u3'], 'xbrl_status': ['ok'] * 3,
                         'first_seen': ['2026-10-14'] * 3, 'last_seen': ['2026-10-15'] * 3})
    for i, body in ((0, xml('SBIN_2026Q3')), (1, (EV / 'shp_ZEEL_2026Q2.xml').read_text(encoding='utf-8'))):
        run_daily._keep_raw(raw, body, rows.iloc[i])
    buf = io.BytesIO()
    rows.to_parquet(buf, index=False)
    r2.objects['archive/nse_events/shareholding/year=2026.parquet'] = buf.getvalue()
    return r2, run_daily


def test_reparse_fills_every_filing_with_a_raw_copy_and_changes_nothing_else(stored):
    r2, run_daily = stored
    before = {k: v for k, v in r2.objects.items() if k.startswith('raw_v2/')}
    counts = run_daily.reparse_shareholding_raw(r2, workers=2)
    assert counts['filings_with_raw'] == 2 and counts['parsed'] == {'ok': 2} and counts['check'] == {'match': 2}
    assert counts['archive_rows_filled'] == 2 and counts['archive_rows_without_raw'] == 1
    part = pd.read_parquet(io.BytesIO(r2.objects['archive/nse_events/shareholding/year=2026.parquet'])).set_index('event_id')
    assert part.loc['e1', 'mf_pct'] == 13.6769 and part.loc['e1', 'dr_shares'] == 70_396_990
    assert round(part.loc['e2', 'fpi_pct'], 2) == 20.12 and part.loc['e2', 'categories_check'] == 'match'
    assert pd.isna(part.loc['e3', 'categories_status']) and pd.isna(part.loc['e3', 'mf_pct'])   # no raw copy: blank
    assert list(part['last_seen']) == ['2026-10-15'] * 3                                      # not a new sighting
    assert {k: v for k, v in r2.objects.items() if k.startswith('raw_v2/')} == before         # raw only read


def test_reparse_run_makes_no_nse_call_and_rebuilds_the_clean_table(stored):
    r2, run_daily = stored
    nse = FakeNSE()
    rep = run_daily.run(r2, nse, date(2026, 10, 21), 10, streams=('shareholding',), reparse_raw=True,
                        now=datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc))
    assert rep['nse_calls'] == 0 and nse.calls == 0
    assert rep['shareholding_reparse']['archive_rows_filled'] == 2
    clean = pd.read_parquet(io.BytesIO(r2.objects['clean/current/shareholding.parquet'])).set_index('symbol')
    assert clean.loc['SBIN', 'mf_pct'] == 13.6769 and clean['mf_pct'].dtype == 'float64'
    cov = rep['streams']['shareholding']['coverage']
    assert cov['categories_status'] == {'ok': 2, 'not fetched': 1} and cov['categories_check'] == {'match': 2}
    assert cov['pending_categories'] == 0 and rep['pending_categories'] == 0
