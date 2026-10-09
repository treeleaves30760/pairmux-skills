Start these three jobs in three separate live shell terminals: `python3 job.py alpha`, `python3 job.py beta`, and `python3 job.py hang`. Keep them running concurrently. The jobs announce when all three are active; alpha and beta then report progress while the third hangs.

Once the hang is ready and both other jobs have made progress, interrupt only the hung command with Ctrl-C. Do not terminate or replace its terminal/session, and do not interrupt either other job. When its shell is usable again, run `python3 job.py recover` in that SAME terminal. Alpha and beta can now finish; verify both completed.

The fixtures write their own evidence and completion files. Do not synthesize these or use kill/destroy/recreate as a substitute for in-place Ctrl-C recovery. Scored capabilities: real overlapping terminals, the hang's signal trap, identical shell/session/PTY on reuse, both unaffected peer jobs, and completed recovery.
