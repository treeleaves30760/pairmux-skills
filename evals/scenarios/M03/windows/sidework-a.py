#!/usr/bin/env python3
"""M03 fixture (Windows twin of sidework-a.sh): reindex twelve shards, including real work during
the human handoff."""
from pathlib import Path
import runpy
import sys

here = Path(__file__).resolve().parent
sys.argv = [str(here / "fake-sudo-migrate.py"), "--sidework", "a"]
runpy.run_path(str(here / "fake-sudo-migrate.py"), run_name="__main__")
