"""Study universe: Rs 100 Cr and up (insiders_clean/universe.py)."""
import pandas as pd

from insiders_clean import universe


def test_universe_table_and_report():
    s = pd.DataFrame({'isin': ['A', 'B', 'C', 'A'], 'display_name': ['Big', 'Small', 'Unknown', 'Big'],
                      'market_cap': [250e7, 40e7, None, 250e7]})
    u = universe.table(s)
    assert list(u['in_universe']) == [True, False, False] and list(u['why']) == ['', 'under Rs 100 Cr', 'no market cap']
    assert u['company'].iloc[0] == 'Big'
    assert universe.report(u) == {'min_market_cap': 100e7, 'isins': 3, 'in_universe': 1, 'under_cutoff': 1, 'no_market_cap': 1}
