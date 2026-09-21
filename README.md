# panda

The smallest agent harness that still does real work — ten files, zero
third-party dependencies, pure Python 3.10+.

## Setup

Put your key in `panda-key.sh` (already gitignored), then **source** it —
running it directly (`./panda-key.sh`) won't export the variable to your
shell:

```bash
source panda-key.sh
```

## Running

**Interactive REPL** (policy defaults to `safe` — approves non-read tools):

```bash
python3 -m panda
```

Quit with **Ctrl-D** (not `exit` — that's just sent to the agent as a task).


**Resume** the most recent interrupted session:

```bash
python3 -m panda -d /tmp/myproject --resume
```