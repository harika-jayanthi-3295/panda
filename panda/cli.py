"""
Day 5 – CLI
Teaches : turning a library into an end-user tool — headless batch mode and
          an interactive REPL in fewer than 200 lines, all stdlib.
Design  : argparse owns option parsing; _print_event is a single closure so
          headless and interactive share identical output; signal handling in
          the REPL catches Ctrl-C cleanly without corrupting the session log.
"""
import argparse, signal, sys, textwrap
from .harness  import Harness
from .security import Policy

# ANSI dim/reset — no-op when stdout is not a tty.
_DIM   = "\033[2m"  if sys.stdout.isatty() else ""
_RESET = "\033[0m"  if sys.stdout.isatty() else ""
_BOLD  = "\033[1m"  if sys.stdout.isatty() else ""


def _make_event_printer():
    """Return an on_event callback that pretty-prints assistant and tool events."""
    def on_event(kind: str, payload) -> None:
        if kind == "assistant":
            text = payload.get("text", "")
            if text:
                print(text)
        elif kind == "tool_start":
            name = payload.get("name", "?")
            args = {k: str(v)[:60] for k, v in payload.get("args", {}).items()}
            arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            print(f"{_BOLD}» {name}({arg_str}){_RESET}")
        elif kind == "tool_end":
            result = str(payload.get("result", ""))
            first_line = result.split("\n")[0][:120]
            print(f"{_DIM}  {first_line}{_RESET}")
    return on_event


def _make_approver():
    """Return a before_tool callback that prompts for human approval."""
    def approver(call: dict):
        name = call.get("name", "?")
        args = {k: str(v)[:80] for k, v in call.get("args", {}).items()}
        arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
        print(f"\n{_BOLD}approve {name}({arg_str}) ?{_RESET} [y/N] ", end="", flush=True)
        try:
            answer = input().strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            return f"User denied {name}"
        return None
    return approver


def _build_harness(args, headless: bool) -> Harness:
    """Construct a Harness from parsed CLI arguments."""
    if args.mode:
        mode = args.mode
    elif headless:
        mode = "yolo"
    else:
        mode = "safe"

    if mode == "safe":
        policy = Policy("safe", approver=_make_approver())
    elif mode == "read-only":
        policy = Policy("read-only")
    else:
        policy = Policy("yolo")

    return Harness(
        workdir=args.workdir,
        model=args.model or None,
        policy=policy,
        on_event=_make_event_printer(),
        max_turns=args.max_turns,
    )


def main(argv=None) -> None:
    """Entry point: headless when -p/--prompt given, else interactive REPL."""
    ap = argparse.ArgumentParser(
        prog="panda",
        description="Minimal agent harness — zero dependencies.",
    )
    ap.add_argument("-p", "--prompt",  metavar="TASK",  help="headless task")
    ap.add_argument("-d", "--workdir", metavar="DIR",   default=".", help="working directory (default: .)")
    ap.add_argument("-m", "--model",   metavar="MODEL", help="model override")
    ap.add_argument("--mode", choices=["safe", "yolo", "read-only"],
                    help="policy mode (default: safe interactive, yolo headless)")
    ap.add_argument("--resume",    action="store_true", help="resume latest session")
    ap.add_argument("--max-turns", type=int, default=120, metavar="N",
                    help="max agent turns per run (default: 120)")
    args = ap.parse_args(argv)

    headless = bool(args.prompt)
    harness  = _build_harness(args, headless)

    if args.resume:
        loaded = harness.resume()
        if loaded:
            print(f"Resumed {len(harness.messages)} messages from {harness.session_path}")
        else:
            print("No session found — starting fresh.")

    # ── Headless ──────────────────────────────────────────────────────────
    if headless:
        result = harness.run(args.prompt)
        print(result)
        sys.exit(0)

    # ── Interactive REPL ──────────────────────────────────────────────────
    mode_label = args.mode or "safe"
    print(f"{_BOLD}panda{_RESET}  model={harness.model}  mode={mode_label}  jail={harness.workdir}")
    print("Ctrl-D to quit · Ctrl-C to interrupt a run (session log is preserved)\n")

    _interrupted = False

    def _handle_sigint(sig, frame):
        nonlocal _interrupted
        _interrupted = True

    signal.signal(signal.SIGINT, _handle_sigint)

    while True:
        try:
            task = input("panda> ").strip()
        except EOFError:
            print()
            break
        if not task:
            continue

        _interrupted = False
        try:
            result = harness.run(task)
        except KeyboardInterrupt:
            _interrupted = True
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue

        if _interrupted:
            path = harness.session_path or "unknown"
            print(f"\n[interrupted — session log is safe; use --resume to continue: {path}]")
        else:
            print(f"\n{result}")
