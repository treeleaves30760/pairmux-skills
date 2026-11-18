#!/usr/bin/env python3
"""M01 fixture (Windows twin of slowtests.sh): 42 real checks across 18 batches; a live readiness
checkpoint. Runs bigserver.py's suite in this same process, as the POSIX script's exec does."""
from pathlib import Path
import runpy
import sys

here = Path(__file__).resolve().parent
sys.argv = [str(here / "bigserver.py"), "--suite"]
runpy.run_path(str(here / "bigserver.py"), run_name="__main__")
