"""Clean a filing's extracted text before a model sees it (to-do 4.14, owner: mandatory).

The cache keeps the raw `pdftotext -layout` text. This turns it into what carries information, with rules that can
be counted and changed without another download:

  1. page breaks become blank lines; every line loses its leading and trailing blanks (layout padding is ~39% of
     the characters of a filing); a run of 3 or more spaces inside a line, a table's column gap, becomes ' | ' so a
     row still reads left to right; shorter runs become one space; runs of blank lines become one;
  2. page furniture: a line that repeats exactly (only a page number inside it may differ) on 3 or more pages of a
     document of 3 or more pages (running headers and footers) is kept once, at its first appearance (a table's
     column header stays), and a line that is only a page number ('Page 3 of 12', '3', '- 3 -') goes;
  3. the exchanges' own address lines in the 'To, The Manager, BSE Limited / National Stock Exchange ...' block that
     opens almost every filing letter (Phiroze Jeejeebhoy Towers, Dalal Street, Exchange Plaza, Bandra Kurla Complex);
  4. the letterhead's contact lines (Registered / Corporate Office, CIN, Tel, Fax, E-mail, Website) in the first 25
     and last 12 lines of the document, and only when the filing's subject is not about an office, an address or
     the registrar (then they are the content).

Nothing else is removed: no sentence, no table cell, no number outside those lines. `clean` returns the text and
what each rule removed (characters), so a run can say where the saving came from.
"""
from __future__ import annotations

import re
from collections import Counter

PAGE_NUMBER = re.compile(r'^(?:page\s*)?[-–—\s]*\d{1,4}\s*(?:(?:of|/)\s*\d{1,4})?[-–—\s]*$', re.IGNORECASE)
EXCHANGE_ADDRESS = re.compile(
    r'phiroze\s+jeejeebhoy|dalal\s+street|exchange\s+plaza|bandra[\s-]*kurla\s+complex|'
    r'bandra\s*\(e\)|p\.\s*j\.\s*towers|^\s*mumbai\s*[-–]\s*400\s*0?(?:01|51)\s*$|'
    r'listing\s+(?:department|compliance)|^\s*the\s+(?:manager|secretary|general\s+manager)\b.{0,60}$', re.IGNORECASE)
LETTERHEAD = re.compile(
    r'^\s*(?:regd\.?|registered|corporate|head)\s*(?:&\s*corporate\s*)?office\b|^\s*cin\s*[:\-]|^\s*(?:tel|telephone|phone|ph|fax|'
    r'mobile)\s*(?:no\.?)?\s*[:\-+0-9(]|^\s*e-?mail\s*(?:id)?\s*[:\-]|^\s*website\s*[:\-]|^\s*(?:https?://|www\.)\S+\s*$',
    re.IGNORECASE)
OFFICE_SUBJECT = re.compile(r'office|address|registrar|rta|share\s+transfer\s+agent|contact', re.IGNORECASE)
HEAD_LINES, TAIL_LINES = 25, 12


def _key(line: str) -> str:
    """The line as compared across pages: exact, except that 'Page 3 of 12' is the same line on every page."""
    return re.sub(r'\bpage\s*\d+(?:\s*(?:of|/)\s*\d+)?', 'page #', line, flags=re.IGNORECASE).lower()


def clean(text: str, subject: str | None = None) -> tuple[str, dict]:
    """(cleaned text, characters removed by rule)."""
    removed = Counter()
    before = len(text or '')
    if not text:
        return '', {}
    pages = text.split('\f')
    lines_by_page = []
    for p in pages:
        lines = []
        for ln in p.splitlines():
            ln = ln.strip()
            ln = re.sub(r' {3,}', ' | ', ln)
            ln = re.sub(r' {2}', ' ', ln)
            lines.append(ln)
        lines_by_page.append(lines)
    removed['padding'] = before - sum(len(x) for x in ('\n'.join(l) for l in lines_by_page)) - 0
    # page furniture: repeated lines, page numbers
    if len(pages) >= 3:
        seen = Counter(k for lines in lines_by_page for k in {_key(x) for x in lines if x})
        furniture = {k for k, n in seen.items() if n >= 3 and len(k) > 1}
    else:
        furniture = set()
    kept_pages, shown_once = [], set()
    for lines in lines_by_page:
        out = []
        for ln in lines:
            key = _key(ln)
            if ln and (PAGE_NUMBER.match(ln) or (key in furniture and key in shown_once)):
                removed['page furniture'] += len(ln) + 1
                continue
            if ln and key in furniture:
                shown_once.add(key)
            out.append(ln)
        kept_pages.append(out)
    flat = [ln for lines in kept_pages for ln in lines + ['']]
    # the exchanges' address lines (whole document) and the letterhead's contact lines (head and tail only)
    keep_letterhead = bool(subject and OFFICE_SUBJECT.search(subject))
    nonblank = [i for i, ln in enumerate(flat) if ln]
    head, tail = set(nonblank[:HEAD_LINES]), set(nonblank[-TAIL_LINES:])
    out = []
    for i, ln in enumerate(flat):
        if ln and EXCHANGE_ADDRESS.search(ln) and len(ln) < 110:
            removed['exchange address'] += len(ln) + 1
            continue
        if ln and not keep_letterhead and (i in head or i in tail) and LETTERHEAD.match(ln) and len(ln) < 160:
            removed['letterhead contacts'] += len(ln) + 1
            continue
        out.append(ln)
    text_out = re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip()
    removed['padding'] = max(before - len(text_out) - sum(v for k, v in removed.items() if k != 'padding'), 0)
    return text_out, {k: int(v) for k, v in removed.items() if v}
