# Terminal control notes (tmux)

This environment provides `tmux` for driving real terminals: long-running programs, interactive
prompts, REPLs, and anything that needs a PTY. A dedicated tmux server socket is reserved for you
in the environment variable `EVAL_TMUX_SOCKET` — pass it to every tmux command with `-L`.

```bash
T() { tmux -L "$EVAL_TMUX_SOCKET" "$@"; }   # define once per shell for brevity
```

## Sessions and windows

```bash
T new-session -d -s work                  # create a detached session (first use starts the server)
T new-window  -t work -n build            # one window per concurrent job
T list-panes -a -F '#{pane_id} #{window_name} #{pane_current_command}'
T kill-server                             # tear everything down when finished
```

## Running commands

Type into a pane with `send-keys`; `-l` sends literal text (no key-name expansion), then send Enter:

```bash
T send-keys -t work:build -l 'make -j4'
T send-keys -t work:build Enter
```

## Reading output

`capture-pane` prints the pane's screen; `-p` to stdout, `-S` reaches back into scrollback history:

```bash
T capture-pane -p -t work:build                 # current screen
T capture-pane -p -S -2000 -t work:build        # include up to 2000 lines of history
```

For long or busy output, log the pane to a file continuously and read the file instead:

```bash
T pipe-pane -t work:build -o 'cat >> /tmp/build.log'
```

## Knowing when a command is done

The shell gives no signal through tmux, so mark completion yourself: append an unmistakable
sentinel that carries the exit code, then poll for it.

```bash
T send-keys -t work:build -l 'make -j4; echo "DONE-MARKER exit=$?"'
T send-keys -t work:build Enter
until T capture-pane -p -S -200 -t work:build | grep -q 'DONE-MARKER exit='; do
  sleep 2
done
T capture-pane -p -S -200 -t work:build | grep 'DONE-MARKER exit='   # read the code
```

Poll with short sleeps in a loop as above — do not guess one long sleep, and do not assume
silence means completion (the program may be waiting for input). Check the last lines of the pane
when output goes quiet: a trailing `Password:`, `[y/N]`, or pager `--More--` means it wants input,
not that it finished.

## Interactive programs

Answer prompts with `send-keys` into the pane that is asking:

```bash
T send-keys -t work:deploy -l 'yes'
T send-keys -t work:deploy Enter
T send-keys -t work:pager q                     # keys without -l: named/literal keys like q
T send-keys -t work:stuck C-c                   # control keys interrupt a hung command
```

Never type or guess a secret (passwords, tokens, PINs). A human can type into the same pane: give
them the socket (`$EVAL_TMUX_SOCKET`) and the pane target (`work:deploy` or a `%N` pane id) and
wait for their confirmation.

## Hygiene

- One window per concurrent job keeps output streams from interleaving.
- Scrollback is finite: capture with a generous `-S` or `pipe-pane` to a file before it scrolls away.
- Quote carefully: prefer `send-keys -l '<exact text>'` followed by a separate `Enter`.
- Kill panes/windows you are done with; `kill-server` at the very end.
