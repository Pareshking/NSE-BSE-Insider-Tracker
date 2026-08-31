import os
from datetime import date, timedelta

# This validator intentionally delegates acquisition to the existing BSE capture
# and records the requested historical window explicitly.  It is kept BSE-only.
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "90"))
target = os.getenv("TARGET_DATE") or date.today().isoformat()
end = date.fromisoformat(target)
start = end - timedelta(days=LOOKBACK_DAYS - 1)
print(f"BSE_ONLY_LOOKBACK_DAYS={LOOKBACK_DAYS}")
print(f"BSE_ONLY_START_DATE={start.isoformat()}")
print(f"BSE_ONLY_END_DATE={end.isoformat()}")
print("BSE-only workflow reached historical validation gate")
