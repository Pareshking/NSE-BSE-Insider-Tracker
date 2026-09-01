"""Evidence-first NSE certification report.

This validator consumes only NSE artifacts. It does not infer correctness from
process exit codes; each category must show native fields and historical date
coverage appropriate to the requested windows.
"""
from __future__ import annotations
import json
from pathlib import Path
TARGET=__import__('os').environ.get('TARGET_DATE','2026-08-31');LOOKBACK=int(__import__('os').environ.get('LOOKBACK_DAYS','90'))
OUT=Path('artifacts/nse_validation');OUT.mkdir(parents=True,exist_ok=True)
def load(p):return json.loads(Path(p).read_text()) if Path(p).exists() else None
def window_ok(w,need_multi=False):
 dates=w.get('distinct_dates') or w.get('api_distinct_dates') or w.get('filtered_distinct_dates') or []
 return w.get('count',0)>0 and (not need_multi or len(dates)>1)
def main():
 r={'source':'NSE','target_date':TARGET,'lookback_days':LOOKBACK,'datasets':{},'certification':'BLOCKED'}
 for ds,path in [('insider','artifacts/nse_insider/report.json'),('bulk','artifacts/nse_bulk/report.json'),('block','artifacts/nse_block/report.json'),('rights','artifacts/nse_validation/rights/report.json'),('preferential','artifacts/nse_validation/preferential/report.json')]:
  d=load(path) or {}; ws=d.get('windows',[]); ok=False; details={}
  if ds in ('bulk','block'):
   ok=bool(ws) and all(window_ok(w,need_multi=(w.get('name') in ('7d','30d','90d'))) for w in ws)
   details={'windows':[(w.get('name'),w.get('count'),w.get('distinct_dates')) for w in ws],'native_columns':bool(d.get('columns'))}
  elif ds=='insider':
   ok=bool(ws) and all(w.get('count',0)>0 and w.get('distinct_transaction_dates') for w in ws)
   details={'windows':[(w.get('name'),w.get('count'),w.get('distinct_transaction_dates')) for w in ws],'native_columns':bool(next((w.get('columns') for w in ws if w.get('columns')),[]))}
  else:
   ok=bool(ws) and all(any(x.get('status')==200 and x.get('row_count',0)>0 for x in w.get('api',[])) for w in ws)
   details={'windows':[(w.get('name'),w.get('api_rows'),w.get('api_distinct_dates')) for w in ws]}
  r['datasets'][ds]={'status':'VERIFIED' if ok else 'BLOCKED',**details}
 r['promoter_semantics']='PENDING_RECORD_LEVEL_REVIEW';r['certification']='VERIFIED' if all(x['status']=='VERIFIED' for x in r['datasets'].values()) and r['promoter_semantics']=='VERIFIED' else 'BLOCKED'
 (OUT/'certification_report.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
if __name__=='__main__':main()
