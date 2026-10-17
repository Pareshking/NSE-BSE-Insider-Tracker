"""One company's call, presentation and results filings with their cached text (read-only).

ISINS=comma list. For each: the archive rows since 1 May 2026 whose subject mentions a call, transcript, presentation, results or press
release, with date, subject, size, and the first 700 characters of the cached text. Writes nothing; no model, no exchange.
"""
from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from r2_writer import r2_client  # noqa: E402
from clean_writer import read_parquet  # noqa: E402
from insiders_clean import filing_text  # noqa: E402

KEEP = re.compile(r'call|transcript|presentation|result|press release|analyst|earnings', re.I)


def main() -> int:
    r2 = r2_client()
    isins = {x.strip() for x in os.environ.get('ISINS', '').split(',') if x.strip()}
    out = []
    frames = []
    for ex in ('nse', 'bse'):
        for m in (5, 6, 7, 8, 9, 10):
            df = read_parquet(r2, f'archive/announcements/{ex}/year=2026/month={m:02d}.parquet')
            if df is not None and not df.empty:
                frames.append(df.assign(exchange=ex))
    arch = pd.concat(frames, ignore_index=True)
    arch = arch[arch['isin'].astype(str).isin(isins) & arch['subject'].astype(str).str.contains(KEEP)]
    arch['broadcast_date'] = arch['broadcast_date'].astype(str).str[:10]
    arch = arch.sort_values(['isin', 'broadcast_date'])
    days = {}
    for isin, g in arch.groupby('isin'):
        out += [f'## {g["company"].iloc[0]} ({isin}): {len(g)} filings', '']
        for r in g.to_dict('records'):
            key = (r['exchange'], r['broadcast_date'])
            if key not in days:
                days[key] = {x['event_id']: x for x in filing_text.load_day(r2, *key).to_dict('records')}
            rec = days[key].get(r['event_id']) or {}
            text = re.sub(r'\s+', ' ', str(rec.get('text') or ''))
            out.append(f'- {r["broadcast_date"]} {r["exchange"]} `{r["event_id"]}` | {str(r.get("subject"))[:70]} | {rec.get("chars")} chars, {rec.get("pages")} pages | {r.get("file_url")}')
            if len(text) > 3000:
                out.append(f'  > {text[:700]}')
        out.append('')
    text = '\n'.join(out)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
