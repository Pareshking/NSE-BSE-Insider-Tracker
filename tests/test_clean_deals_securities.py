"""Deals, securities and the end-to-end run.

BSE deal rows are written in the shape scripts/bse_validate.py's normalize()
produces (security_code = BSE's numeric code, company = BSE's short scrip
name). Their numbers are test values, not real deals, except where noted.
"""
from __future__ import annotations

import json

import pandas as pd
from conftest import BSE_ROWS, RUN_DATE, canonical

from insiders_clean.calendar import seed_state
from insiders_clean.deals import clean_deals
from insiders_clean.entities import entity_key
from insiders_clean.insider import clean_insider
from insiders_clean.pipeline import run
from insiders_clean.securities import display_name


def bse_deal(code, name, client, side, qty, price, day='06/10/2026'):
    return {'event_date': day, 'security_code': code, 'security_name': name, 'company': name,
            'person': client, 'side': side, 'quantity': str(qty), 'price': str(price), 'raw': []}


# --- 3. ACMEUNIV: same-day tranches by one client ------------------------------

def test_same_day_tranches_roll_up(master, report):
    rows = [bse_deal('599999', 'ACMEUNIV', 'SOME FUND LLP', 'BUY', 100000, 112.0),
            bse_deal('599999', 'ACMEUNIV', 'Some Fund LLP', 'BUY', 150000, 108.0),
            bse_deal('599999', 'ACMEUNIV', 'SOME FUND LLP.', 'BUY', 100000, 113.0),
            bse_deal('599999', 'ACMEUNIV', 'OTHER TRADER', 'SELL', 350000, 110.0)]
    out = clean_deals(canonical('bse', 'bulk_deals', rows), master, report, RUN_DATE)
    buy = out[out['side'] == 'BUY'].iloc[0]
    assert len(out) == 2 and buy['trades'] == 3
    assert buy['quantity'] == 350000
    assert round(buy['price'], 4) == round((100000 * 112 + 150000 * 108 + 100000 * 113) / 350000, 4)
    assert buy['counterparties'] == 'Other Trader'
    assert report.data['tables']['deals']['rolled_up_rows'] == 2


def test_same_trade_in_bulk_and_block_feeds_is_one_row(master, report):
    trade = [bse_deal('544717', 'CLEANMAX', 'AUGMENT INDIA I HOLDINGS LLC', 'SELL', 1000000, 1015.5),
             bse_deal('544717', 'CLEANMAX', 'BIG BUYER FUND', 'BUY', 1000000, 1015.5)]
    raw = pd.concat([canonical('bse', 'bulk_deals', trade), canonical('bse', 'block_deals', trade)])
    out = clean_deals(raw, master, report, RUN_DATE)
    assert len(out) == 2 and set(out['feeds']) == {'block,bulk'}
    assert report.data['tables']['deals']['removed']['same_trade_in_both_feeds']['count'] == 2


# --- 5. Clean Max: BSE's cut-off name resolves to the one master record --------

def test_bse_short_name_resolves_by_code(master, report):
    rows = [bse_deal('544717', 'Clean Max Enviro En Sol L', 'AUGMENT INDIA I HOLDINGS LLC', 'SELL', 10, 1000)]
    d = clean_deals(canonical('bse', 'bulk_deals', rows), master, report, RUN_DATE).iloc[0]
    assert d['isin'] == 'INE647U01026'
    assert d['company'] == 'Clean Max Enviro Energy Solutions'
    assert d['nse_symbol'] == 'CLEANMAX' and d['bse_code'] == '544717'


# --- 6. Unknown codes are kept and reported; SME names resolve -----------------

def test_unknown_code_kept_flagged_and_reported(master, report):
    rows = [bse_deal('599999', 'ACMEUNIV', 'SOME FUND LLP', 'BUY', 1000, 10)]
    d = clean_deals(canonical('bse', 'bulk_deals', rows), master, report, RUN_DATE).iloc[0]
    assert pd.isna(d['isin']) and d['company'] == 'Acmeuniv'
    assert 'unmatched_security' in d['flags'] and d['needs_review']
    assert {'exchange': 'bse', 'symbol': '599999', 'name': 'ACMEUNIV', 'table': 'deals'} in \
        report.data['unmatched_securities']


def test_sme_symbol_resolves_from_nse_sme_list(master):
    assert master.resolve('nse', 'BIRDYS') == ('INE0PC901019', 'symbol')


def test_exchange_list_beats_stale_export_isin(master):
    # The 01 Sep export has Anlon Healthcare as INE0Y8W01017; NSE's list today says INE0Y8W01025.
    assert master.resolve('nse', 'AHCL')[0] == 'INE0Y8W01025'


# --- 4. LEAP India: a value too large for the company is held back -------------

def test_value_over_quarter_of_market_cap_is_flagged(real_nse_rows, master, calendar, report):
    # Test values matching the live site's display (Rs.2,000 Cr = 31.9% of
    # market cap); the real filing wasn't in NSE's current list to fetch.
    row = dict(real_nse_rows[0], symbol='LEAP', companyName='LEAP India Limited', acqName='Promoter Entity',
               personCategory='Promoter', modeOfAcquisition='Market Sale', transactionType='Disposal',
               buyQuantity='', sellquantity='100000000', buyValue='', sellValue='20000000000',
               beforeSharesNo='300000000', afterSharesNo='200000000')
    out = clean_insider(canonical('nse', 'insider_trading', [row]), master, calendar, report, RUN_DATE)
    k = out.iloc[0]
    assert round(k['pct_of_mcap'], 1) == 31.9
    assert 'value_over_25pct_of_mcap' in k['flags'] and k['needs_review']


# --- names -------------------------------------------------------------------

def test_entity_spelling_variants_share_an_id():
    ids = {entity_key(n) for n in ('HRTI PRIVATE LIMITED', 'Hrti Pvt. Ltd.', 'HRTI PVT LTD', 'hrti  pvt ltd')}
    assert len(ids) == 1
    assert entity_key('HRTI PRIVATE LIMITED') != entity_key('HRTI CAPITAL PRIVATE LIMITED')


def test_display_names():
    assert display_name('JAY SHREE TEA & INDUSTRIES LTD') == 'Jay Shree Tea & Industries'
    assert display_name('HCL Technologies Limited') == 'HCL Technologies'
    assert display_name('KESORAM INDUSTRIES LIMITED') == 'Kesoram Industries'


# --- end to end ----------------------------------------------------------------

def test_pipeline_run_produces_tables_and_report(real_nse_rows):
    import pandas as pd
    from conftest import FIXTURES, ROOT
    canon = {('nse', 'insider_trading'): canonical('nse', 'insider_trading', real_nse_rows),
             ('bse', 'bulk_deals'): canonical('bse', 'bulk_deals', [
                 bse_deal('544717', 'CLEANMAX', 'BIG BUYER FUND', 'BUY', 10, 1000)])}
    vr = pd.read_csv(ROOT / 'reference_data' / 'security_master_20260901.csv', dtype=str, keep_default_na=False)
    tables, rep = run(canon, RUN_DATE, seed_state(), vr_master=vr,
                      nse_lists=[pd.read_csv(FIXTURES / 'nse_equity_sample.csv', dtype=str)],
                      market_cap_rows=BSE_ROWS)
    assert set(tables) == {'insider_trades', 'deals', 'securities'}
    t = rep['tables']['insider_trades']
    removed = sum(r['count'] for r in t['removed'].values())
    assert t['input_rows'] == len(real_nse_rows) == t['output_rows'] + removed
    assert {'INE860A01027', 'INE647U01026'} <= set(tables['securities']['isin'])
    json.dumps(rep, default=str)  # the report must serialise as written to R2


def test_balanced_high_volume_client_is_labelled_market_maker(master, report):
    rows = []
    for i in range(25):  # 50 legs in one quarter, buys and sells equal
        day = f'{(i % 28) + 1:02d}/07/2026'
        rows += [bse_deal('544717', 'CLEANMAX', 'FAST DESK LLP', 'BUY', 1000 + i, 100.0, day),
                 bse_deal('544717', 'CLEANMAX', 'FAST DESK LLP', 'SELL', 1000 + i, 100.5,
                          day.replace('/07/', '/08/'))]
    rows.append(bse_deal('544717', 'CLEANMAX', 'PATIENT FUND', 'BUY', 5000, 101.0, '01/07/2026'))
    out = clean_deals(canonical('bse', 'bulk_deals', rows), master, report, RUN_DATE)
    assert out.loc[out['client_name'] == 'Fast Desk LLP', 'client_is_market_maker'].all()
    assert not out.loc[out['client_name'] == 'Patient Fund', 'client_is_market_maker'].any()
    assert report.data['tables']['deals']['market_maker_legs'] == 50
