"""Checks the per-filing cache in nse_insider.py.

    python scripts/test_insider_cache.py

No network and no credentials: NSE's HTTP session and the R2 client are both
stubbed, and every request is counted. The point of the cache is the request
count, so that is what these assert on.

Background: the 2026-08-31 run asked NSE for 1,724 filing details and 1,276
came back empty. Sampling the same code from a clean IP returned 120/120 OK,
and the filing-list endpoint then began answering 403 once enough requests
had been made -- NSE rate-limits by volume. Re-fetching immutable filings is
what was tripping it.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nse_insider as ni  # noqa: E402

XML = (
    '<in-bse-co:NameOfTheCompany>Acme Ltd</in-bse-co:NameOfTheCompany>'
    '<in-bse-co:TypeOfInstrument>Equity</in-bse-co:TypeOfInstrument>'
    '<in-bse-co:NameOfThePerson>R Sharma</in-bse-co:NameOfThePerson>'
    '<in-bse-co:CategoryOfPerson>Promoter</in-bse-co:CategoryOfPerson>'
    '<in-bse-co:SecuritiesAcquiredOrDisposedTransactionType>Buy'
    '</in-bse-co:SecuritiesAcquiredOrDisposedTransactionType>'
    '<in-bse-co:SecuritiesAcquiredOrDisposedNumberOfSecurity>100'
    '</in-bse-co:SecuritiesAcquiredOrDisposedNumberOfSecurity>'
)


class FakeResponse:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Counts detail fetches and can start refusing, like NSE does."""

    def __init__(self, filings, fail_after=None):
        self.filings, self.fail_after = filings, fail_after
        self.detail_requests = 0

    def get(self, url, timeout=None):
        if url == ni.LIST_URL:
            return FakeResponse(json.dumps({"data": self.filings}))
        self.detail_requests += 1
        if self.fail_after is not None and self.detail_requests > self.fail_after:
            return FakeResponse("", status=403)      # rate-limited
        return FakeResponse(XML)


class FakeR2:
    """Just enough S3 surface for load_cache/save_cache."""

    def __init__(self, body=None):
        self.body, self.puts = body, 0

    def get_object(self, Bucket, Key):
        if self.body is None:
            raise RuntimeError("NoSuchKey")
        return {"Body": _Body(self.body)}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.body = Body
        self.puts += 1


class _Body:
    def __init__(self, b):
        self.b = b

    def read(self):
        return self.b


def make_filings(n, day="2026-09-01"):
    return [{"appId": f"app-{i}", "symbol": "ACME", "companyName": "Acme Ltd",
             "broadcastDateTime": "01-Sep-2026 10:00:00",
             "xmlFileName": f"https://nse/x/{i}.xml"} for i in range(n)]


def run(filings, cache_body=None, fail_after=None, with_r2=True):
    """Run main() against stubs; return (report, detail_requests, r2).

    OUT is redirected to a temp directory: main() writes the run evidence,
    and pointing it at the real artifacts/nse_insider would overwrite the
    committed capture from an actual run (which is where the 1,724/448/1,276
    baseline lives).
    """
    session = FakeSession(filings, fail_after=fail_after)
    r2 = FakeR2(cache_body) if with_r2 else None
    ni.session = session
    ni._r2_client = lambda: r2
    ni.TARGET = __import__("datetime").date(2026, 9, 2)
    with tempfile.TemporaryDirectory() as tmp:
        ni.OUT = Path(tmp)
        ni.main()
        report = json.loads((ni.OUT / "report.json").read_text())
    return report, session.detail_requests, r2


CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, cond, detail))
    print(f"{'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  -- ' + detail}")


def main() -> int:
    import os
    for k in ("CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"):
        os.environ.setdefault(k, "test")

    # 1. Cold cache: every filing is fetched, and all of them get cached.
    report, requests_made, r2 = run(make_filings(50))
    check("cold run fetches every filing", requests_made == 50, f"got {requests_made}")
    check("cold run reports no reuse", report["filings_reused_from_cache"] == 0,
          f"got {report['filings_reused_from_cache']}")
    check("cold run writes the cache", r2.puts == 1, f"got {r2.puts} put(s)")
    cached_after_cold = json.loads(r2.body)
    check("every parsed filing is cached", len(cached_after_cold) == 50,
          f"got {len(cached_after_cold)}")

    # 2. Warm cache, same filings: zero detail requests. This is the whole point.
    report, requests_made, _ = run(make_filings(50), cache_body=r2.body)
    check("warm run makes NO detail requests", requests_made == 0, f"got {requests_made}")
    check("warm run reuses all filings", report["filings_reused_from_cache"] == 50,
          f"got {report['filings_reused_from_cache']}")
    check("warm run still produces rows", report["filings_in_window"] == 50
          and len(report.get("windows", [])) > 0, "no rows/windows")
    check("request count reported as list-only", report["nse_requests_made"] == 1,
          f"got {report['nse_requests_made']}")

    # 3. Warm cache plus new filings: only the delta is fetched.
    report, requests_made, _ = run(make_filings(60), cache_body=r2.body)
    check("only the delta is fetched", requests_made == 10, f"got {requests_made}")
    check("delta run reports the reuse", report["filings_reused_from_cache"] == 50,
          f"got {report['filings_reused_from_cache']}")

    # 4. Rate-limited mid-run: failures must NOT be cached, or they would
    #    never be retried and the data would be permanently missing.
    report, requests_made, r2b = run(make_filings(50), fail_after=20)
    cached = json.loads(r2b.body)
    check("rate-limited run caches only what succeeded", len(cached) == 20, f"got {len(cached)}")
    check("rate-limited run reports the failures", report["filings_failed"] == 30,
          f"got {report['filings_failed']}")
    # The retry is the payoff: a later run picks up what the limit ate.
    report, requests_made, _ = run(make_filings(50), cache_body=r2b.body)
    check("next run retries only the failed 30", requests_made == 30, f"got {requests_made}")

    # 5. No credentials: unchanged behaviour, no crash.
    report, requests_made, _ = run(make_filings(15), with_r2=False)
    check("without R2 it fetches everything", requests_made == 15, f"got {requests_made}")
    check("without R2 the cache is reported off", report["filing_cache_enabled"] is False,
          f"got {report['filing_cache_enabled']}")

    # 6. A corrupt cache must degrade to a full fetch, never break the run.
    report, requests_made, _ = run(make_filings(15), cache_body=b"{not json")
    check("corrupt cache falls back to a full fetch", requests_made == 15, f"got {requests_made}")

    failures = [c for c in CHECKS if not c[1]]
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
