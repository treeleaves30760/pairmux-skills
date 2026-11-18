#!/usr/bin/env python3
"""M03 fixture (Windows twin of sidework-b.sh): compact twelve event batches while the migration is
handed off."""
from pathlib import Path
import runpy
import sys

here = Path(__file__).resolve().parent
sys.argv = [str(here / "fake-sudo-migrate.py"), "--sidework", "b"]
runpy.run_path(str(here / "fake-sudo-migrate.py"), run_name="__main__")
