"""Read-only: run the preferential and rights cleaning over the real stored
snapshots and print what comes out (counts, link outcomes, lock-in dates and a
few example rows). Writes nothing. Used before the nightly clean step writes
clean/current/preferential.parquet and rights.parquet for the first time."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from clean_writer import issue_tables  # noqa: E402
from r2_writer import r2_client  # noqa: E402

pd.set_option('display.width', 220)
pd.set_option('display.max_columns', 30)


def main():
    tables, report = issue_tables(r2_client())
    for kind, rep in report.items():
        print(f'\n===== {kind}: {rep}')
        df = tables.get(kind)
        if df is None:
            continue
        print('columns:', list(df.columns))
        ls = df[df['stage'] == 'listing']
        if 'lock_in_promoter_until' in df.columns:
            print('listing records with a promoter lock-in date:', int(ls['lock_in_promoter_until'].notna().sum()),
                  '; with an other-holders lock-in date:', int(ls['lock_in_other_until'].notna().sum()))
            print('allottee categories on matched listing records:',
                  ls.loc[ls['link_status'] == 'linked', 'allottee_category'].value_counts().to_dict())
        for col in ('offer_price', 'shares_allotted', 'trading_approval_date', 'allotment_date', 'listing_date'):
            if col in ls:
                print(f'  listing {col}: filled {ls[col].notna().mean() * 100:.0f}%')
        cols = [c for c in ('posted_on', 'symbol', 'stage', 'link_status', 'allottee_category', 'amount_total', 'offer_price',
                            'shares_allotted', 'trading_approval_date', 'lock_in_promoter_until', 'lock_in_other_until') if c in df.columns]
        print('linked examples:')
        print(ls[ls['link_status'] == 'linked'][cols].head(4).to_string(index=False))
        print('ambiguous examples:')
        print(ls[ls['link_status'] == 'ambiguous'][cols].head(3).to_string(index=False))


if __name__ == '__main__':
    main()
