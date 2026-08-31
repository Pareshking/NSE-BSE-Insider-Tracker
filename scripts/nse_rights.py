"""NSE-only Rights Issue acquisition/probe. Transport and schema remain NSE-specific."""
from __future__ import annotations
import json, os
from datetime import date, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

TARGET = date.fromisoformat(os.getenv("TARGET_DATE", "2026-08-31"))
BASE = "https://www.nseindia.com"
URL = f"{BASE}/companies-listing/corporate-filings-RI"
OUT = Path("artifacts/nse_validation/rights")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"})
    home = s.get(BASE + "/", timeout=25)
    report = {"source": "NSE", "dataset": "rights_issue", "target_date": str(TARGET), "homepage_status": home.status_code, "windows": []}
    for name, start in [("1d", TARGET), ("5d", TARGET - timedelta(days=4)), ("30d", TARGET - timedelta(days=29)), ("1y", TARGET - timedelta(days=364))]:
        r = s.get(URL, params={"from_date": start.strftime("%d-%m-%Y"), "to_date": TARGET.strftime("%d-%m-%Y"), "tabIndex": "equity"}, timeout=40)
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")
        table_info = []
        for t in tables:
            rows = t.find_all("tr")
            values = [[c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])] for row in rows]
            values = [v for v in values if v]
            if values:
                table_info.append({"columns": values[0], "row_count": max(0, len(values)-1), "sample": values[1:4]})
        report["windows"].append({"name": name, "start": str(start), "end": str(TARGET), "status": r.status_code, "bytes": len(r.content), "table_count": len(tables), "tables": table_info, "url": r.url})
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
