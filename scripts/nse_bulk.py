"""NSE Bulk Deals acquisition wrapper, independent from Insider/Block."""
from __future__ import annotations
import os,json
from datetime import date,datetime,timedelta
from pathlib import Path
from nse import NSE
TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31')); LOOKBACK=int(os.getenv('LOOKBACK_DAYS','90')); OUT=Path('artifacts/nse_bulk'); OUT.mkdir(parents=True,exist_ok=True)
with NSE(download_folder=str(OUT),server=True,timeout=40) as nse:
    rows=[]
    for start in [TARGET, TARGET-timedelta(days=6), TARGET-timedelta(days=29), TARGET-timedelta(days=LOOKBACK-1)]:
        name={0:'1d',6:'7d',29:'30d',LOOKBACK-1:'90d'}[ (TARGET-start).days ]
        batch=[dict(x) for x in nse.bulkdeals('bulk_deals',datetime.combine(start,datetime.min.time()),datetime.combine(TARGET,datetime.min.time()))]
        (OUT/f'{name}.json').write_text(json.dumps({'dataset':'bulk_deals','source':'NSE','start_date':str(start),'end_date':str(TARGET),'count':len(batch),'rows':batch},indent=2,default=str))
        rows.extend(batch)
# retain all observations for audit; dedup is a later validation stage
report={'dataset':'bulk_deals','source':'NSE','target_date':str(TARGET),'lookback_days':LOOKBACK,'count':len(rows),'unique_observations':len({json.dumps(r,sort_keys=True,default=str) for r in rows}),'columns':sorted(rows[0]) if rows else [],'rows':rows}
(OUT/'report.json').write_text(json.dumps(report,indent=2,default=str)); print(json.dumps({k:report[k] for k in report if k!='rows'},indent=2))
