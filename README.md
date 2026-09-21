# panda

The smallest agent harness that still does real work — ten files, zero
third-party dependencies, pure Python 3.10+.

## What it is

panda gives you a `Harness` class that wires an LLM provider, sandboxed
filesystem tools, a security policy, session persistence, and optional
sub-agents into a single `run(task)` call.  
The entire core is ≈ 900 lines of stdlib Python.

## Setup

```bash
export CLAUDE_API_KEY="sk-ant-..."   # or PANDA_API_KEY
```

## Running

**Headless** (non-interactive, policy defaults to `yolo`):

```bash
python3 -m panda -p "Create a FastAPI hello-world in src/" -d /tmp/myproject
```

**Interactive REPL** (policy defaults to `safe` — approves non-read tools):

```bash
python3 -m panda -d /tmp/myproject
```

**Resume** the most recent interrupted session:

```bash
python3 -m panda -d /tmp/myproject --resume
```

All three modes understand `--mode {safe,yolo,read-only}`, `--model MODEL`,
and `--max-turns N`.

## Day-by-day anatomy

| Day | Files | Lines | What it teaches |
|-----|-------|-------|-----------------|
| 1 | `provider.py` · `loop.py` | 172 | HTTP layer and agent turn cycle |
| 2 | `tools.py` · `security.py` | +212 | Sandboxed tools and deny-list policy |
| 3 | `context.py` · `memory.py` · `skills.py` | +149 | Compaction, persistent memory, skill loading |
| 4 | `session.py` · `subagent.py` · `harness.py` · `__init__.py` | +241 | Session persistence, sub-agents, public API |
| 5 | `cli.py` · `fleet.py` · `__main__.py` | today | CLI front-door and parallel fleet |

## Registering an extra tool

```python
from panda import Harness, tool

@tool("Return the current UTC time", fmt="strftime format string, e.g. %H:%M")
def utc_time(fmt: str = "%Y-%m-%dT%H:%M:%SZ") -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime(fmt)

h = Harness(workdir="/tmp/myproject", extra_tools=[utc_time])
print(h.run("What time is it and create a file timestamped with that value?"))
```

## Session persistence and resume

Every `run()` call appends messages to a `.jsonl` log under
`.panda/sessions/` in the working directory. If the process is killed, the
next run can load the log with `resume()` — torn-tail recovery and synthetic
"Interrupted" tool results restore a valid call/response pairing automatically.

## Parallel fleet

```python
from panda import Harness, run_fleet

jobs = [
    {"name": "auth",    "workdir": "/tmp/auth",    "task": "Write auth.py …"},
    {"name": "storage", "workdir": "/tmp/storage", "task": "Write storage.py …"},
]

results = run_fleet(jobs, make_harness=lambda wd: Harness(workdir=wd))
for r in results:
    status = "✓" if r["ok"] else "✗"
    print(f"{status} {r['name']}: {r['report'][:80]}")
```
