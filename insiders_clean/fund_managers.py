"""Fund managers named in a fund's own name (design V3, owner 23 Oct): a second, separate reading beside the investor.

The investor (`investor_group`, participants.py) is the same investor under different spellings. A fund family is
different: nine funds of one manager are nine legal entities. This maps a fund's NAME to the manager the name itself
names, from `fund_managers.csv` (pattern, manager, sub_advised, reason; the first matching line wins, so a line that
should win over a broader one goes first). Nothing here merges investors; a name with no line has no manager (blank,
never guessed).

`sub_advised` is `yes` when another sponsor's name leads a fund that names the manager too (for example a trust of a
bank, with the manager named inside it): the manager runs it, the sponsor sells it, and the page says so.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

CSV = Path(__file__).with_name('fund_managers.csv')


def load(path: Path = CSV) -> list[tuple[re.Pattern, str, bool, str]]:
    if not path.exists():
        return []
    with open(path, encoding='utf-8', newline='') as fh:
        return [(re.compile(r['pattern'], re.I), r['manager'], str(r.get('sub_advised', '')).strip().lower() == 'yes',
                 r.get('reason', '')) for r in csv.DictReader(fh) if r.get('pattern') and r.get('manager')]


def manager_of(name, rules=None) -> tuple[str | None, bool, str | None]:
    """(manager, sub_advised, reason) the name itself names, or (None, False, None)."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None, False, None
    for pat, manager, sub, reason in (load() if rules is None else rules):
        if pat.search(str(name)):
            return manager, sub, reason
    return None, False, None


def add_manager_columns(deals: pd.DataFrame, rules=None) -> pd.DataFrame:
    """`manager` and `manager_sub_advised` on a deals frame, read once per distinct client name."""
    if deals is None or deals.empty or 'client_name' not in deals:
        return deals
    rules = load() if rules is None else rules
    codes, uniq = pd.factorize(deals['client_name'])
    read = [manager_of(u, rules) for u in uniq]
    out = deals.copy()
    out['manager'] = [read[c][0] if c >= 0 else None for c in codes]
    out['manager_sub_advised'] = [read[c][1] if c >= 0 else False for c in codes]
    return out


def unmatched(deals: pd.DataFrame | None, n: int = 20, rules=None) -> pd.DataFrame:
    """The fund names with no manager line, largest deal value first: where the next line is worth writing."""
    if deals is None or deals.empty or 'client_name' not in deals:
        return pd.DataFrame(columns=['client_name', 'value', 'type'])
    d = add_manager_columns(deals, rules)
    d = d[d['manager'].isna()]
    if 'client_type' in d:
        d = d[d['client_type'].isin(['mutual_fund', 'fpi', 'insurer', 'pension', 'pms_aif', 'fund_other', 'bank'])]
    g = d.groupby('client_name').agg(value=('value', 'sum'), type=('client_type', 'first') if 'client_type' in d else ('value', 'size'))
    return g.sort_values('value', ascending=False).head(n).reset_index()
