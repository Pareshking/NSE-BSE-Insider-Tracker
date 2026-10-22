"""Who is on the other side of a bulk or block deal: a participant type for
every client, and one investor group for the spellings, share classes and
series of one investor (docs/TODO.md items 23 and 16).

NSE and BSE publish only the client's name, so the type is read from the
name, rule by rule, first match wins. Every row says which rule matched and
how sure it is:

* high   -- the name says what it is ("... MUTUAL FUND", "... LIFE INSURANCE
            COMPANY ...") or the behaviour was measured (market makers,
            `client_is_market_maker`);
* medium -- a strong marker (a foreign vehicle form such as PTE, VCC, PCC,
            LP; a global bank; an AIF word);
* low    -- a weak marker: a broking or trading-style name, a generic
            "fund", or a name that looks like a person's.

Calibrated on 1,653 distinct NSE client names of 12 Jul - 12 Oct 2026. A
domestic AIF and a foreign portfolio investor are often not told apart by
the name ("PINE OAK GLOBAL FUND"); those are `fund_other`, low, not a guess.

The investor group never merges two entity IDs (insiders_clean/entities.py
stays conservative); it is an extra column. It comes from the curated list
`investor_aliases.csv` (each line with its reason) and from two suffix rules:
a share class ("- CLASS B", "CLASS B PARTICIPATING SHARES") and a scheme
series ("- SERIES IIIA") belong to the same investor.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from .entities import entity_display, entity_key
from .missing import is_missing

TYPES = {
    'mutual_fund': 'Mutual fund', 'insurer': 'Insurer', 'pension': 'Pension fund', 'bank': 'Bank',
    'fpi': 'Foreign investor', 'pms_aif': 'AIF / PMS', 'fund_other': 'Fund (other)',
    'prop_hft': 'Market maker', 'broker': 'Broker / trading firm', 'corporate': 'Company',
    'trust': 'Trust', 'individual': 'Individual', 'unknown': 'Unknown',
}
INSTITUTIONAL = ('mutual_fund', 'insurer', 'pension', 'bank', 'fpi', 'pms_aif', 'fund_other')

_GLOBAL_BANKS = (r'SOCIETE GENERALE|BNP PARIBAS|GOLDMAN SACHS|MORGAN STANLEY|CITIGROUP|NOMURA|\bUBS\b|BARCLAYS|'
                 r'J ?P ?MORGAN|MERRILL LYNCH|BOFA|CREDIT SUISSE|BANK OF AMERICA|DEUTSCHE BANK|MACQUARIE|HSBC|STANDARD CHARTERED|CLSA')
# (rule name, type, confidence, pattern on the upper-cased name). Order matters.
RULES = [
    ('mutual fund', 'mutual_fund', 'high', r'MUTUAL FUND|\bMF\b'),
    ('insurer', 'insurer', 'high', r'(LIFE|GENERAL) INSURANCE|INSURANCE (COMPANY|CORPORATION)|ASSURANCE'),
    ('domestic pension', 'pension', 'high', r'NATIONAL PENSION|\bNPS\b|PROVIDENT FUND|EMPLOYEES.{0,20}(PENSION|FUND)'),
    ('sovereign or foreign pension', 'fpi', 'high',
     r'GOVERNMENT OF|INVESTMENT AUTHORITY|NORGES BANK|MONETARY AUTHORITY|PENSION FUND|PENSION PLAN|RETIREMENT'),
    # A global bank's dealing arm (BNP Paribas Financial Markets, Citigroup Global Markets Mauritius) trades for its own
    # book or hedges what it sold clients: a dealer, not an investor with a view (trading audit, 22 Oct 2026). Its ODI
    # account (Societe Generale - ODI) holds the hedge of the P-notes it issued: the same.
    ('global bank dealing arm', 'broker', 'medium', r'(?:' + _GLOBAL_BANKS + r').*(?:\b(?:FINANCIAL|GLOBAL) MARKETS\b|\bODI\b)'),
    ('global bank', 'fpi', 'medium', _GLOBAL_BANKS),
    ('indian bank', 'bank', 'high', r'\bBANK (LIMITED|LTD)\b|\bBANK OF\b'),
    ('AIF or PMS', 'pms_aif', 'medium', r'\bAIF\b|ALTERNATIVE INVESTMENT|PORTFOLIO MANAGEMENT|\bPMS\b|CATEGORY I+\b|'
                                        r'FUND\s*-\s*SERIES|\bSCHEME\b'),
    ('foreign vehicle form', 'fpi', 'medium', r'\bPTE\b|MAURITIUS|\bVCC\b|\bPCC\b|SICAV|\bICAV\b|\bLP\b|\bLLC\b|\bINC\b|'
                                              r'INCORPORATED|\bPLC\b|\bGMBH\b|SINGAPORE|'
                                              r'CAYMAN|\bUS$|MASTER FUND|INDEX FUND|PARTICIPATING SHARES|\bCLASS [A-Z]\b|'
                                              r'FONDS|\bKVG\b|COMMINGLED|EMERGING MARKETS'),
    ('generic fund', 'fund_other', 'low', r'\bFUNDS?\b|\bFND\b'),
    ('broking or trading name', 'broker', 'low', r'SECURITIES|BROKING|BROKERS?\b|STOCK|SHARES|COMMODIT|TRADING|TRADEFIN|'
                                                  r'QUANT|CAPITAL MARKETS?|FINVEST|INVESTRADE|FINSOL'),
    ('trust', 'trust', 'medium', r'\bTRUST\b'),
    ('company form', 'corporate', 'medium', r'\bLIMITED\b|\bLTD\b|\bPRIVATE\b|\bPVT\b|\bLLP\b|CORPORATION|COMPANY|'
                                            r'\bINVESTMENTS?\b|ENTERPRISES?|VENTURES|HOLDINGS?|INDUSTRIES|ADVISORS|'
                                            r'\bFINANCE\b|SERVICES|INFRA|REALTORS|PARTNERS'),
    ('HUF', 'individual', 'high', r'\bHUF\b'),
]
_RULES = [(n, t, c, re.compile(p)) for n, t, c, p in RULES]
_PERSON = re.compile(r'^[A-Z]+( [A-Z]+){1,4}$')  # 2-5 words, letters only


def classify(name) -> tuple[str, str, str]:
    """(type, confidence, rule) for one client name."""
    if is_missing(name):
        return 'unknown', 'low', 'no name'
    s = re.sub(r'\s+', ' ', re.sub(r"[.,'()\-/&]", ' ', str(name).upper())).strip()
    for rule, kind, conf, pat in _RULES:
        if pat.search(s):
            return kind, conf, rule
    if _PERSON.match(s):
        return 'individual', 'low', 'looks like a person'
    return 'unknown', 'low', 'no rule matched'


_SUFFIX = [('share class', re.compile(r'\s*-?\s*\bCLASS [A-Z0-9]+\b.*$', re.IGNORECASE)),
           ('series', re.compile(r'\s*-\s*SERIES\s+[IVXLC0-9]+[A-Z]?\s*$', re.IGNORECASE))]
ALIASES_CSV = Path(__file__).with_name('investor_aliases.csv')


def load_aliases(path: Path = ALIASES_CSV) -> dict:
    """entity key of a spelling -> (group name, reason)."""
    if not path.exists():
        return {}
    with open(path, encoding='utf-8', newline='') as fh:
        return {entity_key(r['spelling']): (r['investor'], r['reason']) for r in csv.DictReader(fh) if r.get('spelling')}


def group_of(name, aliases: dict) -> tuple[str | None, str | None]:
    """(investor group name, rule) for one client name; the name itself when no rule applies."""
    if is_missing(name):
        return None, None
    hit = aliases.get(entity_key(name))
    if hit:
        return hit[0], 'alias'
    for rule, pat in _SUFFIX:
        base = pat.sub('', str(name)).strip()
        if base and base != str(name).strip():
            return entity_display(base), rule
    return entity_display(name), None


def add_participant_columns(deals: pd.DataFrame, aliases: dict | None = None) -> pd.DataFrame:
    """Adds client_type, client_type_confidence, client_type_rule,
    investor_group, investor_group_id and investor_group_rule. A measured
    market maker is `prop_hft`, high, whatever its name says."""
    if deals.empty or 'client_name' not in deals:
        return deals
    aliases = load_aliases() if aliases is None else aliases
    df = deals.copy()
    names = df['client_name']
    codes, uniq = pd.factorize(names)
    typed = [classify(u) for u in uniq]
    grouped = [group_of(u, aliases) for u in uniq]
    pick = lambda vals, i: [vals[c][i] if c >= 0 else None for c in codes]  # noqa: E731
    df['client_type'], df['client_type_confidence'], df['client_type_rule'] = pick(typed, 0), pick(typed, 1), pick(typed, 2)
    mm = df['client_is_market_maker'].astype('boolean').fillna(False) if 'client_is_market_maker' in df else False
    df.loc[mm, ['client_type', 'client_type_confidence', 'client_type_rule']] = ['prop_hft', 'high', 'measured two-way volume']
    df['investor_group'], df['investor_group_rule'] = pick(grouped, 0), pick(grouped, 1)
    df['investor_group_id'] = df['investor_group'].map(lambda g: entity_key(g) if g else None)
    return df


def report(deals: pd.DataFrame) -> dict:
    """Counts for the cleaning report: rows by type and confidence, groups formed."""
    if deals.empty or 'client_type' not in deals:
        return {}
    by = deals.groupby(['client_type', 'client_type_confidence']).size()
    multi = deals.groupby('investor_group_id')['client_id'].nunique()
    return {'rows_by_type': {f'{t}/{c}': int(n) for (t, c), n in by.items()},
            'distinct_clients_by_type': {str(k): int(v) for k, v in deals.drop_duplicates('client_id')['client_type'].value_counts().items()},
            'groups_with_several_ids': int((multi > 1).sum())}
