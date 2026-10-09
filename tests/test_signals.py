import pandas as pd

from insiders_clean import signals


def deal(client, side, value, day='2026-10-01', isin='INE000A01011', mm=False, pct=None):
    return {'date': pd.Timestamp(day), 'isin': isin, 'exchange': 'nse', 'symbol': 'ACME', 'nse_symbol': 'ACME',
            'company': 'Acme', 'market_cap': 1e10, 'is_primary': True, 'client_is_market_maker': mm,
            'client_id': client.lower(), 'client_name': client, 'side': side,
            'signed_value': value if side == 'BUY' else -value, 'pct_of_mcap': pct if pct is not None else value / 1e8}


def test_handshake_nets_each_client_and_leaves_out_market_makers():
    d = pd.DataFrame([deal('Seller', 'SELL', 100e7), deal('Fund', 'BUY', 60e7),
                      deal('Churner', 'BUY', 30e7), deal('Churner', 'SELL', 20e7),  # net buyer of 10 Cr
                      deal('Desk', 'BUY', 500e7, mm=True),
                      deal('Lonely', 'SELL', 5e7, isin='INE000B01011')])  # no buyer that day: no handshake
    trades = pd.DataFrame({'isin': ['INE000A01011'], 'person_id': ['seller'], 'person_role': ['promoter']})
    h = signals.handshakes(d, trades, days=30)
    assert len(h) == 1
    r = h.iloc[0]
    assert r['sellers'] == 'Seller' and r['buyers'] == 'Fund; Churner'
    assert r['matched_value'] == 70e7 and r['seller_is_promoter']
    assert abs(r['pct_of_mcap_sold'] - 10.0) < 1e-9 and r['large']


def test_handshake_empty_when_nobody_is_on_both_sides():
    d = pd.DataFrame([deal('A', 'BUY', 1e7), deal('B', 'BUY', 2e7)])
    assert signals.handshakes(d, None, days=30).empty


def test_revised_note_is_not_part_of_a_name():
    from insiders_clean.entities import entity_display, entity_key
    assert entity_key('Rohan Ranjeet Rajput (Revised)') == entity_key('ROHAN RANJEET RAJPUT')
    assert entity_display('Rohan Ranjeet Rajput (Revised)') == 'Rohan Ranjeet Rajput'
    assert entity_display('ACME HOLDINGS - REVISED') == 'Acme Holdings'
    assert entity_key('Revised Holdings Ltd') == 'revised-holdings-limited'
