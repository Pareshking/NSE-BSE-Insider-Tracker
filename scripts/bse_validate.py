"""Evidence-first BSE validator; never certifies from HTTP success alone."""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime
from pathlib import Path

RAW = Path("artifacts/data_validation_v5/bse_raw.json")
OUT = Path("artifacts/bse_validation")
OUT.mkdir(parents=True, exist_ok=True)

DATE_RE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4})\b")
FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d", "%d %b %y", "%d %b %Y")


def text(x):
    return re.sub(r"\s+", " ", str(x or "").strip())


def expand(row):
    if len(row) == 1 and ("\n" in str(row[0]) or "\t" in str(row[0])):
        out = []
        for line in str(row[0]).replace("\r", "").split("\n"):
            p = [text(x) for x in line.strip().split("\t")]
            if len(p) > 1 and any(p): out.append(p)
        return out or [row]
    return [row]


def dates(row):
    out = []
    for cell in row:
        for match in DATE_RE.findall(text(cell)):
            for fmt in FORMATS:
                try:
                    out.append(datetime.strptime(match, fmt).date().isoformat())
                    break
                except ValueError:
                    pass
    return out


def key(ds, row):
    r = [text(x) for x in row]
    if ds in ("bulk_deals", "block_deals") and len(r) >= 7:
        return tuple(r[i] for i in (0, 1, 3, 4, 5, 6))
    if ds == "insider_trading" and len(r) >= 16:
        return tuple(r[i] for i in (0, 1, 2, 3, 6, 7, 8, 10, 15))
    if ds in ("rights_issue", "preferential_issue"):
        return tuple(x.upper() for x in r[:6])
    return tuple(r)


def normalize(ds, r):
    if ds in ("bulk_deals", "block_deals") and len(r) >= 7:
        side = {"B": "BUY", "S": "SELL"}.get(text(r[4]).upper(), text(r[4]))
        return {"event_date": r[0], "security_code": r[1], "security_name": r[2], "company": r[2], "person": r[3], "side": side, "quantity": r[5], "price": r[6], "raw": r}
    if ds == "insider_trading" and len(r) >= 16:
        return {"security_code": r[0], "company": r[1], "person": r[2], "category": r[3], "holding_before": r[4], "security_type": r[5], "quantity": r[6], "value": r[7], "side": r[8], "holding_after": r[9], "acquisition_date": r[10], "mode": r[11], "remarks": r[12:15], "broadcast_date": r[15], "raw": r}
    return {"raw": r}


def collect_pages(obj):
    rows = []
    for page in obj.get("pages", []):
        for raw in page.get("rows", []):
            rows.extend(x for x in expand(raw) if x)
    return rows


def collect_details(obj):
    rows = []
    for page in obj.get("detail_pages", []):
        for raw in page.get("rows", []):
            rows.extend(x for x in expand(raw) if x)
    return rows


def strip_headers(rows):
    out = []
    for r in rows:
        h = " ".join(text(x).lower() for x in r)
        if ("deal date" in h and "security code" in h) or ("security code" in h and "company name" in h) or h.startswith("company name ip stage"):
            continue
        out.append(r)
    return out


def main():
    if not RAW.exists(): raise SystemExit(f"Missing {RAW}")
    src = json.loads(RAW.read_text(encoding="utf-8"))
    start, end = src.get("start_date"), src.get("target_date")
    report = {"source": "BSE", "capture_start": start, "capture_end": end, "lookback_days": src.get("lookback_days"), "datasets": {}, "certification": "BLOCKED"}

    for ds, obj in src.get("datasets", {}).items():
        rows = strip_headers(collect_pages(obj))
        details = strip_headers(collect_details(obj))
        unique, seen, dup = [], {}, []
        for r in rows:
            k = key(ds, r); h = hashlib.sha1(json.dumps(k, ensure_ascii=False).encode()).hexdigest()
            if h in seen: dup.append({"duplicate_of": seen[h], "key": k, "raw": r})
            else: seen[h] = len(unique); unique.append(r)
        dts = sorted({d for r in rows for d in dates(r)})
        sem = {}
        if ds in ("bulk_deals", "block_deals"):
            eligible = [r for r in rows if len(r) >= 7]
            sem = {"native_columns_present": bool(eligible), "has_direction": bool(eligible) and all(text(r[4]).upper() in ("B", "S", "BUY", "SELL") for r in eligible), "buy_rows": sum(text(r[4]).upper() in ("B", "BUY") for r in eligible), "sell_rows": sum(text(r[4]).upper() in ("S", "SELL") for r in eligible)}
        elif ds == "insider_trading":
            eligible = [r for r in rows if len(r) >= 16]
            sem = {"native_columns_present": bool(eligible), "has_person": bool(eligible) and all(text(r[2]) for r in eligible), "has_category": bool(eligible) and all(text(r[3]) for r in eligible), "acquisition_rows": sum(text(r[8]).upper() == "ACQUISITION" for r in eligible), "disposal_rows": sum(text(r[8]).upper() == "DISPOSAL" for r in eligible), "promoter_group_rows": sum(text(r[3]).upper() == "PROMOTER GROUP" for r in eligible)}
        elif ds in ("rights_issue", "preferential_issue"):
            sem = {"index_rows": len(rows), "detail_pages": len(obj.get("detail_pages", [])), "detail_rows": len(details), "detail_dates": sorted({d for r in details for d in dates(r)}), "detail_nonempty": bool(details)}
        hist = obj.get("historical_date_test", {})
        historical_change = hist.get("status") == "changed"
        report["datasets"][ds] = {"raw_rows": len(rows), "unique_rows": len(unique), "duplicate_rows": len(dup), "distinct_dates": dts, "earliest_date": dts[0] if dts else None, "latest_date": dts[-1] if dts else None, "historical_test": hist, "historical_range_applied": historical_change, "semantics": sem, "normalized_file": str(OUT / f"{ds}_normalized.json"), "status": "PENDING"}
        (OUT / f"{ds}_normalized.json").write_text(json.dumps([normalize(ds, r) for r in unique], indent=2, ensure_ascii=False), encoding="utf-8")

    for ds in ("insider_trading", "bulk_deals", "block_deals"):
        x = report["datasets"].get(ds, {})
        x["status"] = "VERIFIED" if x.get("raw_rows", 0) > 0 and x.get("historical_range_applied") and x.get("semantics", {}).get("native_columns_present") and x.get("distinct_dates") else "BLOCKED"
    for ds in ("rights_issue", "preferential_issue"):
        x = report["datasets"].get(ds, {})
        x["status"] = "VERIFIED" if x.get("raw_rows", 0) > 0 and x.get("semantics", {}).get("detail_nonempty") else "BLOCKED"
    report["certification"] = "VERIFIED" if all(report["datasets"].get(ds, {}).get("status") == "VERIFIED" for ds in ("insider_trading", "bulk_deals", "block_deals", "rights_issue", "preferential_issue")) else "BLOCKED"
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__": main()
