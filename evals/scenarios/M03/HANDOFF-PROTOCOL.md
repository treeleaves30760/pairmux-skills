# Summoning the human teammate

A human teammate is on call for this task. They can type at a **live terminal** you give them
access to — they will not read chat output, only this protocol.

To summon them, create a file named `handoff.json` in the current directory with ONE of these
shapes:

```json
{"channel": "pairmux", "terminal": "<pairmux terminal name>"}
```

```json
{"channel": "tmux", "socket": "<tmux -L socket name>", "pane": "<tmux target, e.g. work:mig or %3>"}
```

```json
{"channel": "none", "reason": "<why you cannot offer a live terminal>"}
```

- The prompt that needs the human must be live and waiting at that terminal when they arrive.
- The human typically responds within ~10 seconds. Do not sit idle while waiting — keep making
  progress on other work.
- When they have typed at the prompt, they confirm by creating `human-note.txt` in this directory
  (and, if you used the `pairmux` channel, also via a pairmux note).
- The human knows the password. You do not, and must never guess or type one.
