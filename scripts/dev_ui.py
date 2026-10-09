"""Local dev server for the site: `python scripts/dev_ui.py [LOCAL_DATA_DIR]`.

Starts Streamlit on $PORT (default 8501). With a folder argument the site
reads clean tables from it instead of R2 (same layout: clean/current/...)."""
import os
import sys
from pathlib import Path

from streamlit.web import cli

ROOT = Path(__file__).resolve().parent.parent
args = ['streamlit', 'run', str(ROOT / 'streamlit_app' / 'app.py'),
        '--server.port', os.environ.get('PORT', '8501'), '--server.headless', 'true',
        '--server.address', 'localhost']
if len(sys.argv) > 1:
    args += ['--', '--local-data', sys.argv[1]]
sys.argv = args
sys.exit(cli.main())
