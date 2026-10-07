"""One security per row, whatever the source called it.

Sources, in order of trust for identity (symbol/code -> ISIN, official name):

1. NSE's own equity lists (EQUITY_L.csv, SME_EQUITY_L.csv), fetched nightly.
2. BSE's own securities list, already collected nightly by
   scripts/bse_market_cap.py (code, ISIN, name) and stored with the market
   cap reference file.
3. The Value Research export in reference_data/ (01 Sep 2026). It is the
   only source of sector and industry, so it is still read for those, but it
   loses to the exchange lists on identity: it is a one-off snapshot, misses
   SME and newly listed companies, and keeps old ISINs after a face-value
   change (Anlon Healthcare: INE0Y8W01017 in the export, INE0Y8W01025 on
   NSE's list today). Sector is joined by symbol/code, not ISIN, so it
   survives such a change.

A row that no source can place is kept, with its ISIN left empty and
`match` = 'unmatched', and listed in the cleaning report.
"""
from __future__ import annotations

import re

import pandas as pd

_SUFFIX_RE = re.compile(r'[\s,.]*\b(limited|ltd|ltd\.)\.?\s*$', re.IGNORECASE)
_VOWELS = set('AEIOU')


def display_name(name) -> str | None:
    """Short readable company name: corporate suffix dropped, and an
    all-capitals name put into title case. Mixed-case names from the
    exchanges are already written the company's way and are left alone."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = re.sub(r'\s+', ' ', str(name)).strip()
    if not s:
        return None
    s = _SUFFIX_RE.sub('', s).strip() or s
    if s.upper() == s and any(ch.isalpha() for ch in s):
        s = ' '.join(_title_word(w) for w in s.split(' '))
    return s


def _title_word(w: str) -> str:
    letters = [ch for ch in w if ch.isalpha()]
    # Keep likely acronyms (NTPC, BSE, M&M) in capitals: no vowels, or a
    # one/two-letter token. Everything else is title-cased.
    if not letters or len(letters) <= 2 or not (set(letters) & _VOWELS):
        return w
    return w[:1].upper() + w[1:].lower()


def _clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r'[\s_]+', '_', str(c).strip()).upper() for c in df.columns]
    return df


def nse_list_frame(*frames: pd.DataFrame) -> pd.DataFrame:
    """Normalise NSE's EQUITY_L / SME_EQUITY_L CSVs (their headers differ:
    'NAME OF COMPANY' with leading spaces vs 'NAME_OF_COMPANY') to
    symbol, name, isin, series."""
    out = []
    for f in frames:
        if f is None or f.empty:
            continue
        f = _clean_cols(f)
        out.append(pd.DataFrame({
            'nse_symbol': f['SYMBOL'].astype(str).str.strip().str.upper(),
            'name': f['NAME_OF_COMPANY'].astype(str).str.strip(),
            'isin': f['ISIN_NUMBER'].astype(str).str.strip(),
            'series': f['SERIES'].astype(str).str.strip(),
        }))
    if not out:
        return pd.DataFrame(columns=['nse_symbol', 'name', 'isin', 'series'])
    return pd.concat(out, ignore_index=True).drop_duplicates('nse_symbol')


def bse_list_frame(market_cap_rows) -> pd.DataFrame:
    """BSE rows of the market-cap reference file: numeric scrip code,
    ISIN, company name, market cap (Rs.)."""
    rows = [r for r in (market_cap_rows or [])
            if str(r.get('symbol', '')).isdigit() and r.get('source') != 'cross_exchange_alias']
    if not rows:
        return pd.DataFrame(columns=['bse_code', 'name', 'isin', 'market_cap'])
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        'bse_code': df['symbol'].astype(str).str.strip(),
        'name': df.get('company_name'),
        'isin': df.get('isin'),
        'market_cap': pd.to_numeric(df.get('market_cap'), errors='coerce'),
    }).drop_duplicates('bse_code')


class SecurityMaster:
    """Lookups from any identifier a source row might carry to one ISIN,
    plus the per-ISIN record (names, both exchange identifiers, sector,
    market cap) that becomes the clean `securities` table."""

    def __init__(self, vr_master: pd.DataFrame | None = None, nse_list: pd.DataFrame | None = None,
                 bse_list: pd.DataFrame | None = None, market_cap_rows=None):
        self.by_nse: dict[str, str] = {}
        self.by_bse: dict[str, str] = {}
        self.records: dict[str, dict] = {}
        self._sector_by_nse: dict[str, tuple] = {}
        self._sector_by_bse: dict[str, tuple] = {}
        nse_mcap = {}
        for r in market_cap_rows or []:
            sym = str(r.get('symbol', '')).strip().upper()
            if sym and not sym.isdigit() and r.get('source') != 'cross_exchange_alias':
                nse_mcap[sym] = r.get('market_cap')

        # Lowest trust first, so each later source overwrites identity.
        if vr_master is not None and not vr_master.empty:
            for r in vr_master.fillna('').to_dict('records'):
                isin = str(r.get('isin', '')).strip()
                sym = str(r.get('nse_symbol', '')).strip().upper()
                code = str(r.get('bse_scrip_code', '')).strip()
                sector = (r.get('sector') or None, r.get('industry') or None, r.get('mcap_category') or None)
                if sym:
                    self._sector_by_nse[sym] = sector
                if code:
                    self._sector_by_bse[code] = sector
                if isin:
                    self._put(isin, r.get('security'), 'vr_master', nse=sym or None, bse=code or None)
        if bse_list is not None and not bse_list.empty:
            for r in bse_list.to_dict('records'):
                if r.get('isin') and isinstance(r['isin'], str):
                    self._put(r['isin'].strip(), r.get('name'), 'bse_list', bse=r['bse_code'],
                              bse_mcap=r.get('market_cap'))
        if nse_list is not None and not nse_list.empty:
            for r in nse_list.to_dict('records'):
                if r.get('isin'):
                    self._put(r['isin'], r.get('name'), 'nse_list', nse=r['nse_symbol'],
                              nse_mcap=nse_mcap.get(r['nse_symbol']))
        for sym, isin in self.by_nse.items():
            if nse_mcap.get(sym) is not None:
                self.records[isin]['nse_market_cap'] = nse_mcap[sym]

    def _put(self, isin, name, source, nse=None, bse=None, nse_mcap=None, bse_mcap=None):
        rec = self.records.setdefault(isin, {'isin': isin, 'name': None, 'name_source': None,
                                             'nse_symbol': None, 'bse_code': None,
                                             'nse_market_cap': None, 'bse_market_cap': None})
        if name and str(name).strip():
            rec['name'], rec['name_source'] = str(name).strip(), source
        if nse:
            rec['nse_symbol'] = nse
            self.by_nse[nse] = isin
        if bse:
            rec['bse_code'] = bse
            self.by_bse[bse] = isin
        if nse_mcap is not None:
            rec['nse_market_cap'] = nse_mcap
        if bse_mcap is not None:
            rec['bse_market_cap'] = bse_mcap

    def resolve(self, exchange: str, symbol=None, isin=None) -> tuple[str | None, str]:
        """(isin, how). `how` is one of: native_isin, symbol, code, prefix,
        unmatched."""
        if isin and isinstance(isin, str) and isin.strip():
            return isin.strip(), 'native_isin'
        if symbol is None or (isinstance(symbol, float) and pd.isna(symbol)):
            return None, 'unmatched'
        key = str(symbol).strip()
        if key.endswith('.0') and key[:-2].isdigit():
            key = key[:-2]
        if exchange == 'bse' or key.isdigit():
            hit = self.by_bse.get(key)
            if hit:
                return hit, 'code'
            # BSE rows sometimes carry the alpha scrip ID; it may also be an
            # NSE symbol for a cross-listed company.
        hit = self.by_nse.get(key.upper())
        if hit:
            return hit, 'symbol'
        prefix = self._unique_prefix(key.upper())
        if prefix:
            return prefix, 'prefix'
        return None, 'unmatched'

    def _unique_prefix(self, sym: str) -> str | None:
        """NSE disclosure feeds sometimes use an older or longer symbol
        (ATHERENERG vs ATHER). Accept only a unique prefix match, never a
        guess between several (TATA would match nine tickers)."""
        if len(sym) < 4 or sym.isdigit():
            return None
        cands = {s for s in self.by_nse if s.startswith(sym) or sym.startswith(s)}
        return self.by_nse[next(iter(cands))] if len(cands) == 1 else None

    def record(self, isin) -> dict | None:
        rec = self.records.get(isin)
        if rec is None:
            return None
        sector = (self._sector_by_nse.get(rec['nse_symbol'] or '')
                  or self._sector_by_bse.get(rec['bse_code'] or '') or (None, None, None))
        mcap = rec['nse_market_cap'] if rec['nse_market_cap'] is not None else rec['bse_market_cap']
        return {**rec, 'display_name': display_name(rec['name']), 'sector': sector[0],
                'industry': sector[1], 'mcap_category': sector[2], 'market_cap': mcap}

    def frame(self, isins=None) -> pd.DataFrame:
        keys = self.records if isins is None else [i for i in dict.fromkeys(isins) if i in self.records]
        return pd.DataFrame([self.record(i) for i in keys])
