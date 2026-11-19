"""SAST Reg 29 rows whose holder is not an investor: held back from the signal pages with a reason. No I/O.

A Reg 29 row names a holder, a mode and a move. Three kinds of row read as a buy or a sale on the pages but are not
one (Today, 19 Nov 2026):

* A lender's trustee or security agent (SECURITY_HOLDER; a mutual fund's trustee filing for a scheme is an investor,
  FUND_TRUSTEE), or a mode that says pledge, encumbrance or release: shares held as security,
  an encumbrance event, not a purchase ("Catalyst Trusteeship Limited acting as Debenture Trustee on behalf of
  Debenture holders" in Medplus Health Services, "Bought +2.83%, 17.27% -> 20.10%"). `holder_kind` 'lender' (by
  name) and `held_back_reason` 'lender_or_trustee' or 'encumbrance_mode'.
* A law firm filing on someone's behalf ("Azb & Partners" in Tribhovandas Bhimji Zaveri, promoter, sold 74.12% to
  0.00%, mode Others): the firm holds nothing; the row is a filing artefact until read. `holder_kind`
  'filing_agent', reason 'filed_by_law_firm'.
* A promoter whose whole stake of 70% or more goes to 0% with mode "Others": a scheme, a merger of a holding company
  or a data-entry error far more often than a sale; held back for a look, reason
  'promoter_whole_stake_out_mode_others'.

Nothing is deleted: the rows stay in the clean table with the two columns; the pages show a lender row as an
encumbrance and keep held-back rows off Today, counted. Names are matched by the patterns below, never by
similarity; a filing agent is a named law firm or a word only a law firm uses (advocates, solicitors).
"""
from __future__ import annotations

import re

import pandas as pd

# A SAST filing by a lender's trustee or security agent, or by a bank branch, is a pledge or its release
# (the shares are held as security), not an investor buying or selling: Vedanta's tap bonds (GLAS Agency,
# Citicorp, Kroll, Axis Trustee), Orient Green (Catalyst Trusteeship), Horizon Industrial Parks and Manipal
# (Deutsche Bank AG, Singapore Branch; Vistra ITCL), Oct 2026.
SECURITY_HOLDER = re.compile(r'truste|security agent|\bagent\b|on behalf of|debenture|for the holders|facility agreement'
                             r'|\blenders?\b|\bglas\b|vistra|\bitcl\b|madison pacific|citicorp international'
                             r'|international trust|\bbank\b.*\bbranch\b', re.I)

# A mode that says the shares were pledged, encumbered or released is security, never a stake bought or sold,
# whoever files it: BSE's Reg 29 list holds 224 such non-promoter rows to 21 Oct 2026, 37 by names the trustee
# pattern misses (Deutsche Bank AG for Horizon Industrial Parks, Piramal Pharma, Manipal; Comfort Fincap).
ENCUMBRANCE_MODE = re.compile(r'pledge|encumb|releas|invoc|revoc|non.?disposal|\blien\b', re.I)

# Law firms that file SEBI disclosures for clients (Indian practices that act on takeovers and open offers), and
# words only a law practice uses. "Partners" alone is not one: many funds are "... Partners".
FILING_AGENT = re.compile(
    r'\bazb\b|cyril amarchand|shardul amarchand|amarchand (?:and|&) mangaldas|khaitan (?:and|&) co|\btrilegal\b'
    r'|j\.? ?sagar associates|desai (?:and|&) diwanji|economic laws practice|luthra (?:and|&) luthra|\binduslaw\b'
    r'|talwar thakore|\bs ?(?:and|&) ?r associates\b|\bargus partners\b|saraf (?:and|&) partners|crawford bayley'
    r'|wadia ghandy|\bdsk legal\b|samvad partners|\bphoenix legal\b|\bkochhar (?:and|&) co\b'
    r'|\badvocates?\b|\bsolicitors?\b|attorneys? at law|law offices?\b|law chambers?\b', re.I)

# A mutual fund's trustee company files for its schemes ("HDFC Trustee Company Ltd A/c HDFC Small Cap Fund"): an
# investor, though SECURITY_HOLDER matches "truste". Not a lender unless the name also says it acts for lenders.
FUND_TRUSTEE = re.compile(r'\ba/?c\b|\bfund\b|\bscheme\b|mutual|\bmf\b|portfolio', re.I)
LENDER_WORDS = re.compile(r'debenture|\blenders?\b|security (?:agent|trustee)|facility agreement|for the holders', re.I)

WHOLE_STAKE_MIN_PCT = 70.0     # a promoter move this large ...
ZERO_AFTER_PCT = 0.005         # ... to a stake after of 0% (to 2 decimals) ...
OTHER_MODES = {'others', 'other'}   # ... filed with mode "Others"

REASONS = ('lender_or_trustee', 'encumbrance_mode', 'filed_by_law_firm', 'promoter_whole_stake_out_mode_others')


def _text(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].fillna('').astype(str) if col in df else pd.Series('', index=df.index)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors='coerce') if col in df else pd.Series(float('nan'), index=df.index)


def hold_back(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """(SAST table with `holder_kind` and `held_back_reason`, counts per reason). The first rule that applies gives
    the reason, in the order of REASONS. `holder_kind`: 'lender', 'filing_agent' or 'holder'."""
    df = df.copy()
    if df.empty:
        df['holder_kind'] = pd.Series(dtype=object)
        df['held_back_reason'] = pd.Series(dtype=object)
        return df, {}
    name, mode = _text(df, 'acquirer_name'), _text(df, 'mode').str.strip()
    lender = name.str.contains(SECURITY_HOLDER) & (~name.str.contains(FUND_TRUSTEE) | name.str.contains(LENDER_WORDS))
    agent = name.str.contains(FILING_AGENT) & ~lender
    enc_mode = mode.str.contains(ENCUMBRANCE_MODE)
    promoter = df['is_promoter'].astype('boolean').fillna(False).astype(bool) if 'is_promoter' in df \
        else pd.Series(False, index=df.index)
    moved = _num(df, 'percent_equity_traded')
    sold = _num(df, 'pct_sold').fillna(-moved.where(moved < 0))
    whole_out = (promoter & mode.str.lower().isin(OTHER_MODES) & sold.ge(WHOLE_STAKE_MIN_PCT)
                 & _num(df, 'post_stake_pct').abs().le(ZERO_AFTER_PCT))
    df['holder_kind'] = pd.Series('holder', index=df.index, dtype=object).mask(lender, 'lender').mask(agent, 'filing_agent')
    reason = pd.Series(None, index=df.index, dtype=object)
    for mask, why in ((whole_out, REASONS[3]), (agent, REASONS[2]), (enc_mode, REASONS[1]), (lender, REASONS[0])):
        reason = reason.mask(mask, why)   # applied last-to-first, so the first rule in REASONS wins
    df['held_back_reason'] = reason
    return df, {k: int(v) for k, v in reason.value_counts().items()}
