import pandas as pd

import price_coverage as pc


def test_event_coverage_counts_entry_and_history():
    dates = pd.bdate_range('2026-01-01', periods=300)
    sess = pd.DataFrame({'isin': 'INE1', 'date': dates})
    ev = pd.DataFrame({'isin': ['INE1', 'INE1', 'INE2', ''], 'trade_date_to': ['2026-02-02', '2026-12-30', '2026-02-02', '2026-02-02']})
    r = pc.event_coverage(ev, sess, 'x')
    assert r['events_2026'] == 4 and r['with_isin'] == 3
    assert r['with_entry_price'] == 2 and r['history_ge_20_sessions'] == 2 and r['history_ge_250'] == 1
