"""The short lists behind the Actions page (insiders_clean/actions.py)."""
import pandas as pd

from insiders_clean import actions

REF = pd.Timestamp('2026-10-09')


def trade(person, role, side, value, pct, day, isin='INE000A01011', company='Acme', token=False):
    return {'isin': isin, 'person_id': person.lower(), 'person_name': person, 'person_role': role, 'side': side,
            'value': value, 'pct_of_mcap': pct, 'seen': pd.Timestamp(day), 'company': company,
            'nse_symbol': company.upper(), 'is_token': token}


def frame(*rows):
    return pd.DataFrame(rows)


def test_buying_lists_the_biggest_buyer_first_and_only_the_asked_roles():
    t = frame(trade('Raj', 'promoter', 'BUY', 5e7, 0.20, '2026-10-05'), trade('Raj', 'promoter', 'BUY', 5e7, 0.10, '2026-10-06'),
              trade('Mina', 'director', 'BUY', 2e7, 0.05, '2026-10-07', isin='INE000B01011', company='Beta'),
              trade('Old', 'promoter', 'BUY', 9e7, 0.90, '2026-08-01', isin='INE000C01011', company='Gamma'))
    promoters = actions.buying(t, REF, ('promoter', 'promoter_group'))
    assert list(promoters['person_name']) == ['Raj'] and abs(promoters['pct_30d'].iloc[0] - 0.30) < 1e-9
    assert list(actions.buying(t, REF, ('director', 'kmp'))['person_name']) == ['Mina']


def test_token_buys_are_not_listed():
    t = frame(trade('Raj', 'promoter', 'BUY', 1e6, 0.001, '2026-10-05', token=True))
    assert actions.buying(t, REF, ('promoter',)).empty


def test_selling_needs_25_lakh_and_the_last_30_days():
    t = frame(trade('Raj', 'promoter', 'SELL', 6e7, 0.40, '2026-10-05'), trade('Raj', 'promoter', 'SELL', 1e7, 0.05, '2026-10-06'),
              trade('Small', 'promoter', 'SELL', 1e6, 0.01, '2026-10-05', isin='INE000B01011', company='Beta'),
              trade('Old', 'promoter', 'SELL', 9e7, 0.90, '2026-08-01', isin='INE000C01011', company='Gamma'),
              trade('Buyer', 'promoter', 'BUY', 9e7, 0.90, '2026-10-05', isin='INE000D01011', company='Delta'))
    s = actions.selling(t, REF, ('promoter', 'promoter_group'))
    assert list(s['person_name']) == ['Raj'] and s['value'].iloc[0] == 7e7 and s['trades'].iloc[0] == 2


def test_pledged_lists_high_pledge_and_leaves_out_carried_forward_quarters():
    sh = pd.DataFrame({'symbol': ['AAA', 'BBB', 'CCC', 'AAA'], 'isin': ['I1', 'I2', 'I3', 'I1'],
                       'quarter_end': ['2026-06-30', '2026-06-30', '2026-06-30', '2026-03-31'],
                       'promoter_pledge_pct': [40.0, 20.0, 10.0, 5.0], 'shareholding_stale': [False, True, False, False]})
    sec = pd.DataFrame({'isin': ['I1', 'I3'], 'company': ['Alpha Ltd', 'Gamma Ltd'], 'nse_symbol': ['AAA', 'CCC']})
    p = actions.pledged(sh, sec)
    assert list(p['symbol']) == ['AAA'] and p['company'].iloc[0] == 'Alpha Ltd' and p['promoter_pledge_pct'].iloc[0] == 40.0


def test_pledged_works_on_a_table_without_the_stale_column():
    sh = pd.DataFrame({'symbol': ['AAA'], 'isin': ['I1'], 'quarter_end': ['2026-06-30'], 'promoter_pledge_pct': [40.0]})
    assert list(actions.pledged(sh, None)['company']) == ['AAA']


def test_empty_inputs_give_empty_lists():
    assert actions.buying(pd.DataFrame(), REF, ('promoter',)).empty
    assert actions.selling(None, REF, ('promoter',)).empty
    assert actions.pledged(None, None).empty
