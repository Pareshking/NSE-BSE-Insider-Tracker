"""NSE pledge rows without shares, and BSE's two feeds of one pledge (insiders_clean/insider.py, audit 22 Oct)."""
import pandas as pd

from insiders_clean import insider


def test_an_nse_pledge_without_shares_takes_them_from_its_bse_copy():
    day = pd.Timestamp('2026-09-21')
    who = {'isin': 'INE947N01017', 'person_id': 'melligeri-private-family-foundation', 'kind': 'pledge_create',
           'trade_date_from': day, 'trade_date_to': day, 'broadcast_ts': day}
    df = pd.DataFrame([{**who, 'exchange': 'nse', 'quantity': None, '_bse_csv': False},
                       {**who, 'exchange': 'bse', 'quantity': 100513070.0, '_bse_csv': True},
                       {**who, 'exchange': 'bse', 'quantity': 100513070.0, '_bse_csv': False},
                       {**who, 'exchange': 'nse', 'quantity': None, '_bse_csv': False, 'kind': 'pledge_revoke'}])
    assert insider._pledge_quantity_from_bse(df) == 1
    assert df.loc[0, 'quantity'] == 100513070 and pd.isna(df.loc[3, 'quantity'])   # a release with no copy stays blank
    pairs = insider._pair_copies(df[df['exchange'].eq('nse')].assign(side=None), df[df['exchange'].eq('bse')].assign(side=None))
    assert len(pairs) == 1 and pairs[0][0] == 0
