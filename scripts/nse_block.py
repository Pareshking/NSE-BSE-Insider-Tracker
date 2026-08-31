"""NSE Block Deals acquisition wrapper. Kept independent from Insider/Bulk."""
from __future__ import annotations
import os,json
from datetime import date,datetime
from pathlib import Path
from nse import NSE
TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31')); OUT=Path('artifacts/nse_block'); OUT.mkdir(parents=True,exist_ok=True)
with NSE(download_folder=str(OUT),server=True,timeout=40) as nse:
 rows=[dict(x) for x in nse.bulkdeals('block_deals',datetime.combine(TARGET,datetime.min.time()),datetime.combine(TARGET,datetime.min.time()))]
report={'dataset':'block_deals','source':'NSE','target_date':str(TARGET),'count':len(rows),'columns':sorted(rows[0]) if rows else [],'rows':rows}
(OUT/'report.json').write_text(json.dumps(report,indent=2,default=str)); print(json.dumps({k:report[k] for k in report if k!='rows'},indent=2))
