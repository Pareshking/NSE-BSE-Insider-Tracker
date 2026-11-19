"""Today page data, 19 Nov 2026: SAST holders that are not investors held back with a reason
(insiders_clean/sast.py), Today's SAST selection (screens/proto._today_sast), and the netted two-way deal on the
page. The deals rule itself is tested in test_audit_data_layer.py (same_day_both_sides_netted)."""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd
from conftest import ROOT
from test_nse_events import FakeNSE, events, frame  # noqa: F401 (fixture)

from insiders_clean import bse_events, ideas, sast

sys.path.insert(0, str(ROOT / 'streamlit_app'))


def _row(name, moved, after, promoter=False, mode='Open Market', **kw):
    up = moved > 0
    return dict({'event_id': name, 'acquirer_name': name, 'is_promoter': promoter, 'mode': mode,
                 'action_type': 'Acquisition' if up else 'Sale', 'pct_acquired': moved if up else None,
                 'pct_sold': None if up else -moved, 'percent_equity_traded': moved, 'post_stake_pct': after}, **kw)


def test_a_debenture_trustee_is_a_lender_not_a_buyer():
    """Medplus Health Services, 19 Nov 2026: "Bought +2.83%, 17.27% -> 20.10%" by a debenture trustee."""
    df = pd.DataFrame([_row('Catalyst Trusteeship Limited acting as Debenture Trustee on behalf of Debenture holders', 2.83, 20.10,
                            mode='Others'),
                       _row('Nippon Life India Trustee Ltd A/c Nippon India Small Cap Fund', 2.1, 7.2),   # a fund's trustee: an investor
                       _row('Axis Trustee Services Limited', 5.0, 5.0),
                       _row('Real Investor Fund', 2.5, 6.0)])
    out, counts = sast.hold_back(df)
    assert out.loc[0, 'holder_kind'] == 'lender' and out.loc[0, 'held_back_reason'] == 'lender_or_trustee'
    assert out.loc[1, 'holder_kind'] == 'holder' and pd.isna(out.loc[1, 'held_back_reason'])
    assert out.loc[2, 'holder_kind'] == 'lender'
    assert out.loc[3, 'holder_kind'] == 'holder' and pd.isna(out.loc[3, 'held_back_reason'])
    assert counts == {'lender_or_trustee': 2}
    assert ideas.SECURITY_HOLDER is sast.SECURITY_HOLDER


def test_a_law_firm_holder_and_a_whole_promoter_stake_out_as_others_are_held_back():
    """Tribhovandas Bhimji Zaveri, 19 Nov 2026: "Azb & Partners, Promoter, Sold -74.12%, 74.12% -> 0.00%, Others 29(2)"."""
    df = pd.DataFrame([_row('Azb & Partners', -74.12, 0.0, promoter=True, mode='Others'),
                       _row('Some Promoter Holdings Private Limited', -74.12, 0.0, promoter=True, mode='Others'),
                       _row('Some Promoter Holdings Private Limited', -74.12, 0.0, promoter=True, mode='Open Market'),
                       _row('A Promoter', -40.0, 0.0, promoter=True, mode='Others'),
                       _row('A Promoter', -74.0, 3.0, promoter=True, mode='Others'),
                       _row('Bellwether Partners Fund', 3.0, 8.0)])   # "Partners" alone is not a law firm
    out, counts = sast.hold_back(df)
    assert out.loc[0, 'holder_kind'] == 'filing_agent' and out.loc[0, 'held_back_reason'] == 'filed_by_law_firm'
    assert out.loc[1, 'held_back_reason'] == 'promoter_whole_stake_out_mode_others' and out.loc[1, 'holder_kind'] == 'holder'
    assert out.loc[2:, 'held_back_reason'].isna().all()   # on the market, under 70%, or not to 0%: as filed
    assert counts == {'filed_by_law_firm': 1, 'promoter_whole_stake_out_mode_others': 1}


def test_an_encumbrance_mode_is_held_back_and_nothing_is_deleted():
    df = pd.DataFrame([_row('A Promoter', -3.0, 40.0, promoter=True, mode='Pledge'), _row('X', 2.0, 6.0)])
    out, counts = sast.hold_back(df)
    assert len(out) == 2 and counts == {'encumbrance_mode': 1} and out.loc[0, 'holder_kind'] == 'holder'
    empty, c = sast.hold_back(pd.DataFrame(columns=['acquirer_name', 'mode']))
    assert c == {} and {'holder_kind', 'held_back_reason'} <= set(empty.columns)


def test_held_back_rows_are_not_big_investor_events():
    ref = pd.Timestamp('2026-11-18')
    df = pd.DataFrame([_row('Azb Partners Holdco', 6.0, 6.0, isin='INE000000001', broadcast_date='2026-11-17'),
                       _row('Real Investor Fund', 6.0, 6.0, isin='INE000000002', broadcast_date='2026-11-17')])
    df.loc[0, 'acquirer_name'] = 'AZB & Partners'
    out, _ = sast.hold_back(df)
    ev = ideas.stake_events(out, ref, days=7)
    assert ev['isin'].tolist() == ['INE000000002']


def test_bse_sast_clean_carries_the_reason(master):
    from collectors.bse import parsers as bse_parsers
    rows = [{'scrip_code': '500325', 'Company_Name': 'Reliance', 'shareholdername': 'AZB & Partners',
             'Acquisition_date': '10/11/2026 - 10/11/2026', 'Acq_Sale': 'SALE', 'Acq_sale_qty': '100', 'Acq_sale_Pct': '74.12',
             'Acquisition_After': '0', 'Acquisition_Pct_After': '0.00', 'flag': '29(2)', 'FLD_MODE': 'Others',
             'Fld_NameOfPG': 'Yes', 'NEWDT': '12 Nov 2026', 'Fld_TotDilPerAfterAcq': '0'}]
    arch, _ = bse_parsers.parse_sast(rows)
    clean, counts = bse_events.clean(arch, master, None, 'sast')
    assert clean.loc[0, 'held_back_reason'] == 'filed_by_law_firm' and counts['held_back'] == {'filed_by_law_firm': 1}


def test_nightly_nse_sast_table_carries_the_columns(events):  # noqa: F811
    r2, run_daily = events
    rep = run_daily.run(r2, FakeNSE(), date(2026, 10, 7), 10, streams=('sast',))
    sa = frame(r2, 'clean/current/sast.parquet')
    assert {'holder_kind', 'held_back_reason'} <= set(sa.columns)
    assert isinstance(rep['streams']['sast']['held_back'], dict)


# --- the page: Today's SAST selection and the rows' labels ---------------------------------------------------------------

def _filed(name, trade, filed, **kw):
    return _row(name, 6.0, 6.0, trade_date_to=pd.Timestamp(trade), broadcast_ts=filed, **kw)


def test_today_lists_sast_filed_within_14_days_of_the_trade_and_counts_the_rest():
    """Info Edge / LIC (19 Nov 2026): made public 28 days after a 16 Oct trade, listed on Today. Today keeps deciding by
    the day made public; a filing more than SAST_LATE_DAYS (14) after its trade is counted and left to Stakes, and a
    held-back row is counted, not listed."""
    from screens import proto
    assert proto.SAST_LATE_DAYS == 14
    ref = pd.Timestamp('2026-11-18')
    sa = pd.DataFrame([_filed('Life Insurance Corporation of India', '2026-10-16', '13-Nov-2026 18:00'),   # 28 days late
                       _filed('On Time Fund', '2026-11-12', '14-Nov-2026 10:00'),
                       _filed('Fourteen Days Fund', '2026-10-31', '14-Nov-2026 10:00'),                  # 14 days: listed
                       _filed('Old Filing Fund', '2026-11-01', '01-Nov-2026 10:00'),                     # outside 7 days
                       _filed('Trustee', '2026-11-12', '14-Nov-2026 10:00', held_back_reason='lender_or_trustee')])
    kept, late, held = proto._today_sast(sa, ref)
    assert kept['acquirer_name'].tolist() == ['On Time Fund', 'Fourteen Days Fund']
    assert (late, held) == (1, 1)
    assert proto._today_sast(None, ref) == (None, 0, 0)


def test_stakes_rows_say_encumbrance_or_held_back_instead_of_bought():
    from screens import proto
    sa = pd.DataFrame([_filed('Catalyst Trusteeship', '2026-11-12', '14-Nov-2026 10:00', held_back_reason='lender_or_trustee'),
                       _filed('Azb & Partners', '2026-11-12', '14-Nov-2026 10:00', held_back_reason='filed_by_law_firm'),
                       _filed('Real Fund', '2026-11-12', '14-Nov-2026 10:00')])
    sa['_f'] = pd.to_datetime(sa['broadcast_ts'], format='mixed')
    rows, _, _ = proto._sast_rows(sa, {})
    acts = {r['who'].split('>')[1].split('<')[0]: r['act'] for r in rows}
    assert 'Encumbrance' in acts['Catalyst Trusteeship'] and 'Bought' not in acts['Catalyst Trusteeship']
    assert 'Held back' in acts['Azb &amp; Partners'] and 'law firm' in acts['Azb &amp; Partners']
    assert 'Bought' in acts['Real Fund']


def test_a_netted_deal_line_says_so_and_names_no_self_counterparty():
    from screens import proto
    d = pd.DataFrame([{'date': pd.Timestamp('2026-11-17'), 'isin': 'INE1', 'company': 'Millworks', 'symbol': '544826',
                       'client_name': 'LRSD Capital Private Limited', 'side': 'SELL', 'quantity': 19000.0, 'price': 101.0,
                       'value': 19000 * 101 * 10.0, 'pct_of_mcap': 0.19, 'feeds': 'bulk', 'exchange': 'bse', 'trades': 2,
                       'counterparties': 'Other Buyer Fund', 'client_is_market_maker': False,
                       'two_way_bought': 300000.0, 'two_way_sold': 319000.0}])
    rows, _, _ = proto._deal_rows(d)
    assert 'net of' in rows[0]['who'] and 'other side: Other Buyer Fund' in rows[0]['who']


# --- Vectras Enprocon: two directors, same rupees and % the same day -----------------------------------------------------

def test_the_same_trade_under_two_names_is_counted_not_removed():
    """Two people with the same shares, value and days are possible; the same holdings before and after too would make
    it one trade filed twice. Counted in the report (one filing or two), never merged."""
    from insiders_clean.insider import same_trade_two_names
    base = {'exchange': 'bse', 'isin': 'INE9', 'company': 'Vectras Enprocon', 'side': 'BUY', 'quantity': 100000.0,
            'value': 1.21e7, 'trade_date_from': '2026-11-14', 'trade_date_to': '2026-11-14',
            'holding_before': 500000.0, 'holding_after': 600000.0}
    df = pd.DataFrame([dict(base, person_id='a', person_name='A Director', app_id='1'),
                       dict(base, person_id='b', person_name='B Director', app_id='2'),
                       dict(base, person_id='c', person_name='C Director', app_id='3', holding_before=1.0, holding_after=100001.0)])
    out = same_trade_two_names(df)
    assert out['groups'] == 1 and out['same_filing'] == 0 and out['examples'][0]['names'] == ['A Director', 'B Director']
    df.loc[1, 'app_id'] = '1'
    assert same_trade_two_names(df)['same_filing'] == 1
    assert same_trade_two_names(df.iloc[[0, 2]])['groups'] == 0
