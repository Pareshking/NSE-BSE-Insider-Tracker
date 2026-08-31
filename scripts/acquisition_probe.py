from __future__ import annotations

import json
import os
import time
from datetime import date
from typing import Any

import requests

TARGET_DATE = os.getenv("TARGET_DATE", "2026-08-31")
D = date.fromisoformat(TARGET_DATE)
DDMMYYYY = D.strftime("%d-%m-%Y")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)


def compact(obj: Any) -> Any:
    if isinstance(obj, list):
        return {"type": "list", "count": len(obj), "sample_keys": sorted(obj[0].keys()) if obj and isinstance(obj[0], dict) else []}
    if isinstance(obj, dict):
        return {"type": "dict", "keys": sorted(obj.keys()), "sample": {k: obj[k] for k in list(obj)[:8]}}
    return {"type": type(obj).__name__}


def nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"})
    r = s.get("https://www.nseindia.com/", timeout=20)
    r.raise_for_status()
    return s


def nse_get(s: requests.Session, name: str, url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        r = s.get(url, timeout=30)
        result: dict[str, Any] = {"source": "NSE", "dataset": name, "url": url, "status_code": r.status_code, "elapsed_s": round(time.perf_counter() - started, 3), "content_type": r.headers.get("content-type", ""), "bytes": len(r.content)}
        if r.ok:
            try:
                result["payload"] = compact(r.json())
            except Exception:
                result["payload"] = {"type": "non_json", "prefix": r.text[:200]}
        else:
            result["error_prefix"] = r.text[:300]
        return result
    except Exception as exc:
        return {"source": "NSE", "dataset": name, "url": url, "error": f"{type(exc).__name__}: {exc}"}


def bse_probe() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        from bseindia import equity
        for name, fn in (("bulk_deals", equity.bulk_deal_as_on_today), ("block_deals", equity.block_deal_as_on_today)):
            started = time.perf_counter()
            try:
                data = fn()
                results.append({"source": "BSE", "dataset": name, "method": "bseindia", "status": "success", "elapsed_s": round(time.perf_counter() - started, 3), "count": len(data) if hasattr(data, "__len__") else None, "columns": list(data.columns) if hasattr(data, "columns") else [], "sample": data.head(2).to_dict(orient="records") if hasattr(data, "head") else None})
            except Exception as exc:
                results.append({"source": "BSE", "dataset": name, "method": "bseindia", "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:
        results.append({"source": "BSE", "dataset": "library_import", "method": "bseindia", "status": "error", "error": f"{type(exc).__name__}: {exc}"})

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Referer": "https://www.bseindia.com/"})
    started = time.perf_counter()
    try:
        home = s.get("https://www.bseindia.com/", timeout=20)
        page = s.get("https://www.bseindia.com/corporates/xbrldetails.aspx", timeout=30)
        results.append({"source": "BSE", "dataset": "insider_regulation_7_2", "method": "official_page", "status": "success" if page.ok else "blocked_or_error", "homepage_status": home.status_code, "status_code": page.status_code, "elapsed_s": round(time.perf_counter() - started, 3), "content_type": page.headers.get("content-type", ""), "bytes": len(page.content)})
    except Exception as exc:
        results.append({"source": "BSE", "dataset": "insider_regulation_7_2", "method": "official_page", "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return results


def main() -> int:
    report: dict[str, Any] = {"target_date": TARGET_DATE, "target_date_display": DDMMYYYY, "phase": "1+2 acquisition probe", "results": []}
    try:
        s = nse_session()
        q = f"from={DDMMYYYY}&to={DDMMYYYY}"
        report["results"].extend([
            nse_get(s, "insider_trading", f"https://www.nseindia.com/api/corporates-pit?index=equities&from_date={DDMMYYYY}&to_date={DDMMYYYY}"),
            nse_get(s, "bulk_deals", f"https://www.nseindia.com/api/historical/bulk-deals?{q}"),
            nse_get(s, "block_deals", f"https://www.nseindia.com/api/historical/block-deals?{q}"),
        ])
    except Exception as exc:
        report["results"].append({"source": "NSE", "dataset": "session_bootstrap", "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    report["results"].extend(bse_probe())
    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/acquisition_probe.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
