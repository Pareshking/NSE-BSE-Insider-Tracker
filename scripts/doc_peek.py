"""Print what the reader's text step makes of a few filings (read-only): notes and the first characters. URLS in scripts/peek_urls.txt (id <TAB> url)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import announcement_sample as s  # noqa: E402

for ln in (HERE / 'peek_urls.txt').read_text().splitlines():
    if '\t' not in ln:
        continue
    eid, url = ln.split('\t')[:2]
    try:
        data = s.download(url)
        text, notes = s.text_of(data)
        import re
        keep = [ln for ln in text.splitlines() if re.search(r'revenue|total income|profit|exceptional|ebitda|net worth', ln, re.I)][:25]
        print(f'##### {eid} {url}\nnotes: {notes}\nbytes {len(data)}, head {data[:12]!r}, chars {len(text)}\n{text[:2500]}\n--- figure lines ---\n' + '\n'.join(re.sub(r'\s+', ' ', k)[:200] for k in keep) + '\n')
    except Exception as exc:  # noqa: BLE001
        print(f'##### {eid} FAILED {type(exc).__name__}: {exc}')
