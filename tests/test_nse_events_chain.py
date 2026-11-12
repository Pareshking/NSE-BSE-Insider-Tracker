"""The results backfill chain must not skip a window whose listing failed (12 Nov 2026: NSE timeouts in rounds 5-6
were read as "nothing pending" and the chain moved to older windows, leaving Jul 2025 - Jan 2026 empty)."""
from pathlib import Path

WF = Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'nse-events.yml'


def test_failed_listing_stops_before_the_older_window():
    text = WF.read_text(encoding='utf-8')
    guard = text.index('if [ "$LISTFAIL" -eq 1 ]; then')
    advance = text.index('NFROM=$(date -d "$RFROM - 90 days" +%F)')
    assert guard < advance
    assert "startswith('results: fetch failed')" in text
