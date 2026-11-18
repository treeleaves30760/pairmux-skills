"""Confirmation-prompt fixture for eval S04 (Windows twin of confirm.sh)."""
import sys

sys.stdout.write("Delete all temporary files? [y/N] ")
sys.stdout.flush()
answer = sys.stdin.readline().strip()
print("CONFIRMED-DELETING" if answer in ("y", "Y", "yes", "YES") else "ABORTED", flush=True)
