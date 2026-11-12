"""Write the [theme] block of both Streamlit config files from streamlit_app/ui/theme.py (the one place tokens live).

    python scripts/sync_theme.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'streamlit_app'))
from ui import theme  # noqa: E402

CONFIGS = [ROOT / '.streamlit' / 'config.toml', ROOT / 'streamlit_app' / '.streamlit' / 'config.toml']


def synced(text: str) -> str:
    """The file with its [theme] table replaced (up to the next table), everything else kept."""
    block = theme.theme_toml()
    if re.search(r'^\[theme\]', text, flags=re.M):
        return re.sub(r'^\[theme\]\n(?:(?!^\[).*\n?)*', block + '\n', text, count=1, flags=re.M)
    return block + '\n' + text


if __name__ == '__main__':
    for f in CONFIGS:
        f.write_text(synced(f.read_text(encoding='utf-8')), encoding='utf-8')
        print('wrote', f.relative_to(ROOT))
