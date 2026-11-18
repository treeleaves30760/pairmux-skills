"""Minimal pager for eval S07 on Windows (no `less` there): shows a 500-line report, then waits
at an `(END)` prompt for q, exactly like less at the end of its input."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import termsupport  # noqa: E402

for number in range(1, 501):
    print(number)
sys.stdout.write("(END)")
sys.stdout.flush()
with termsupport.KeyReader() as keys:
    while keys.read().lower() != "q":
        pass
sys.stdout.write("\r     \r")
sys.stdout.flush()
