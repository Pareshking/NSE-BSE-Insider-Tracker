from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from typing import Any

import pandas as pd
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


def nse_direct(s: requests.Session, name: str, url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        r = s.get(url, timeout=30)
        result = {"source": "NSE", "dataset": name, "method": "direct_api", "url": url, "status_code": r.status_code, "elapsed_s": round(time.perf_counter() - started, 3), "content_type": r.headers.get("content-type", ""), "bytes": len(r.content)}
        if r.ok:
            try:
                result["payload"] = compact(r.json())
            except Exception:
                result["payload"] = {"type": "non_json", "prefix": r.text[:200]}
        else:
            result["error_prefix"] = r.text[:300]
        return result
    except Exception as exc:
        return {"source": "NSE", "dataset": name, "method": "direct_api", "url": url, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def nse_server_library() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from nse import NSE
        with NSE(download_folder="artifacts/nse", server=True, timeout=30) as nse:
            for kind in ("bulk_deals", "block_deals"):
                started = time.perf_counter()
                try:
                    rows = nse.bulkdeals(kind, datetime.combine(D, datetime.min.time()), datetime.combine(D, datetime.min.time()))
                    out.append({"source": "NSE", "dataset": kind, "method": "nse_package_server", "status": "success", "elapsed_s": round(time.perf_counter() - started, 3), "count": len(rows), "sample_keys": sorted(rows[0].keys()) if rows else []})
                except Exception as exc:
                    out.append({"source": "NSE", "dataset": kind, "method": "nse_package_server", "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:
        out.append({"source": "NSE", "dataset": "library_import", "method": "nse_package_server", "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return out


def bse_probe() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    try:
        import bseindia.equity as equity
        for name, fn in (("bulk_deals", equity.bulk_deal_as_on_today), ("block_deals", equity.block_deal_as_on_today)):
            started = time.perf_counter()
            try:
                data = fn()
                results.append({"source": "BSE", "dataset": name, "method": "bseindia", "status": "success", "elapsed_s": round(time.perf_counter() - started, 3), "count": len(data) if hasattr(data, "__len__") else None, "columns": list(data.columns) if hasattr(data, "columns") else [], "sample": data.head(2).to_dict(orient="records") if hasattr(data, "head") else None})
            except Exception as exc:
                results.append({"source": "BSE", "dataset": name, "method": "bseindia", "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:
        results.append({"source": "BSE", "dataset": "bseindia_import", "method": "bseindia", "status": "error", "error": f"{type(exc).__name__}: {exc}"})

    try:
        from bse import BSE
        started = time.perf_counter()
        with BSE(download_folder="artifacts/bse") as bse:
            code = bse.getScripCode("TCS")
        results.append({"source": "BSE", "dataset": "api_reachability", "method": "BseIndiaApi", "status": "success", "elapsed_s": round(time.perf_counter() - started, 3), "tcs_code": code})
    except Exception as exc:
        results.append({"source": "BSE", "dataset": "api_reachability", "method": "BseIndiaApi", "status": "error", "error": f"{type(exc).__name__}: {exc}"})

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Referer": "https://www.bseindia.com/"})
    started = time.perf_counter()
    try:
        home = s.get("https://www.bseindia.com/", timeout=20)
        page = s.get("https://www.bseindia.com/corporates/xbrldetails.aspx", timeout=30)
        tables = []
        if page.ok:
            try:
                tables = pd.read_html(page.text)
            except Exception:
                tables = []
        text_lower = page.text.lower()
        results.append({"source": "BSE", "dataset": "insider_regulation_7_2", "method": "official_page", "status": "success" if page.ok else "blocked_or_error", "homepage_status": home.status_code, "status_code": page.status_code, "elapsed_s": round(time.perf_counter() - started, 3), "content_type": page.headers.get("content-type", ""), "bytes": len(page.content), "html_table_count": len(tables), "contains_insider_text": "insider" in text_lower, "contains_regulation_7_2": "7(2)" in text_lower})
    except Exception as exc:
        results.append({"source": "BSE", "dataset": "insider_regulation_7_2", "method": "official_page", "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return results


def main() -> int:
    os.makedirs("artifacts/nse", exist_ok=True)
    os.makedirs("artifacts/bse", exist_ok=True)
    report: dict[str, Any] = {"target_date": TARGET_DATE, "target_date_display": DDMMYYYY, "phase": "1+2 acquisition probe", "results": []}
    try:
        s = nse_session()
        q = f"from={DDMMYYYY}&to={DDMMYYYY}"
        report["results"].extend([
            nse_direct(s, "insider_trading", f"https://www.nseindia.com/api/corporates-pit?index=equities&from_date={DDMMYYYY}&to_date={DDMMYYYY}"),
            nse_direct(s, "bulk_deals", f"https://www.nseindia.com/api/historical/bulk-deals?{q}"),
            nse_direct(s, "block_deals", f"https://www.nseindia.com/api/historical/block-deals?{q}"),
        ])
    except Exception as exc:
        report["results"].append({"source": "NSE", "dataset": "session_bootstrap", "method": "direct_api", "status": "blocked_or_error", "error": f"{type(exc).__name__}: {exc}"})
    report["results"].extend(nse_server_library())
    report["results"].extend(bse_probe())
    with open("artifacts/acquisition_probe.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
