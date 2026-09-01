"""Gap detection + backfill for missed daily runs.

If the scheduled r2-storage.yml run fails outright on some weekday (Actions
outage, a step erroring before r2_writer.py runs), no manifests/{date}.json
ever gets written for that day -- a permanent hole in R2's manifests/
prefix, even though the very next successful run's 90-day lookback fetch
already contains that day's transactions somewhere inside it. The frontend
keys everything by manifest date, so a user picking that date finds nothing,
even though the underlying data was never actually lost.

This doesn't need a new fetch: nse_insider.py/nse_bulk.py/etc. already pull
a 90-day window every run, and r2_writer.py's get_rows() returns that WHOLE
window regardless of TARGET_DATE -- TARGET_DATE only controls the R2 key
path and manifest filename. So backfilling a missed weekday is just
re-running r2_writer.py once more with TARGET_DATE set to the missing date,
reusing the exact artifacts this run already fetched. No extra NSE/BSE
calls, no extra rate-limit exposure.

Scope: only checks the last BACKFILL_LOOKBACK_DAYS weekdays (default 10),
not the full 90-day window -- an old gap from months back is a historical
question for VALIDATION_STATUS.md, not something to silently paper over
here every single run. Weekends are skipped outright (nothing trades);
a real holiday still gets "backfilled" with that day's data folded into a
run for a date with genuinely zero disclosures -- flagged in the manifest
as backfilled so the Data Quality page can show it came from a catch-up
run, not a same-day capture, rather than pretending otherwise.
"""
from __future__ import annotations
import json, os, subprocess, sys
from datetime import date, datetime, timedelta

import boto3

BUCKET = os.environ['R2_BUCKET_NAME']
TARGET_DATE = date.fromisoformat(os.environ.get('TARGET_DATE', str(date.today())))
LOOKBACK_DAYS = int(os.environ.get('BACKFILL_LOOKBACK_DAYS', '10'))


def r2_client():
    return boto3.client(
        's3',
        endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto',
    )


def existing_manifest_dates(client) -> set[str]:
    dates = set()
    paginator = client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=BUCKET, Prefix='manifests/'):
        for obj in page.get('Contents', []):
            name = obj['Key'].rsplit('/', 1)[-1]
            if name.endswith('.json'):
                dates.add(name[:-len('.json')])
    return dates


def recent_weekdays(latest: date, n: int) -> list[date]:
    out, d = [], latest - timedelta(days=1)  # today's own date was just written by the normal run
    while len(out) < n:
        if d.weekday() < 5:  # Mon-Fri
            out.append(d)
        d -= timedelta(days=1)
    return out


def main():
    client = r2_client()
    have = existing_manifest_dates(client)
    candidates = recent_weekdays(TARGET_DATE, LOOKBACK_DAYS)
    missing = [d for d in candidates if str(d) not in have]

    print(f'Checked last {LOOKBACK_DAYS} weekdays before {TARGET_DATE}: '
          f'{len(candidates) - len(missing)}/{len(candidates)} already have a manifest.')
    if not missing:
        print('No gaps to backfill.')
        return

    print(f'Backfilling {len(missing)} missing date(s): {[str(d) for d in missing]}')
    for d in missing:
        print(f'\n--- Backfilling {d} (reusing this run\'s already-fetched data) ---')
        env = {**os.environ, 'TARGET_DATE': str(d)}
        result = subprocess.run([sys.executable, 'scripts/r2_writer.py'], env=env)
        if result.returncode != 0:
            print(f'  WARNING: backfill write for {d} exited {result.returncode}; leaving gap for next run to retry.')
            continue
        # Mark the manifest as a backfill so it's never confused with a
        # same-day capture -- the data is real, but it was observed later.
        try:
            obj = client.get_object(Bucket=BUCKET, Key=f'manifests/{d}.json')
            manifest = json.loads(obj['Body'].read())
            manifest['backfilled'] = True
            manifest['backfilled_from_run_date'] = str(TARGET_DATE)
            manifest['backfilled_at'] = datetime.now().isoformat()
            client.put_object(
                Bucket=BUCKET, Key=f'manifests/{d}.json',
                Body=json.dumps(manifest, indent=2, default=str).encode('utf-8'),
                ContentType='application/json',
            )
            print(f'  Backfilled {d}, marked manifest as backfilled_from_run_date={TARGET_DATE}.')
        except Exception as exc:
            print(f'  WARNING: wrote {d} but could not stamp it as backfilled: {exc}')


if __name__ == '__main__':
    main()
