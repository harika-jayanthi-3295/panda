import argparse, signal, sys, textwrap
from .harness  import Harness
from .security import Policy

# Short names accepted by /model; anything else is passed through as-is.
_MODEL_ALIASES = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
    "opus":   "claude-opus-5",
    "fable":  "claude-fable-5-1",
}

# ANSI styling — no-op when stdout is not a tty.
_isatty = sys.stdout.isatty()
_DIM    = "\033[2m"  if _isatty else ""
_RESET  = "\033[0m"  if _isatty else ""
_BOLD   = "\033[1m"  if _isatty else ""
_CYAN   = "\033[36m" if _isatty else ""   # user's own input (the prompt)
_GREEN  = "\033[32m" if _isatty else ""   # panda's replies
_RED    = "\033[31m" if _isatty else ""   # approval prompts asking the user for input


def _summarize_call(call: dict) -> str:
    """One-line human summary of a tool call, for the approval prompt."""
    name, args = call.get("name", "?"), call.get("args", {})
    detail = (args.get("path") or args.get("command") or args.get("task")
              or args.get("note") or args.get("title"))
    if detail is None:
        detail = ", ".join(f"{k}={str(v)[:30]!r}" for k, v in args.items())
    detail = str(detail).replace("\n", " ").strip()
    if len(detail) > 60:
        detail = detail[:60] + "…"
    return f"{name}: {detail}" if detail else name


def _make_event_printer():
    """Return an on_event callback that pretty-prints assistant and tool events."""
    def on_event(kind: str, payload) -> None:
        if kind == "assistant":
            text = payload.get("text", "")
            if text:
                print(f"{_GREEN}{_BOLD}⏺{_RESET} {_GREEN}{text}{_RESET}")
        elif kind == "tool_start":
            name = payload.get("name", "?")
            args = {k: str(v)[:60] for k, v in payload.get("args", {}).items()}
            arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            print(f"{_DIM}» {name}({arg_str}){_RESET}")
        elif kind == "tool_end":
            result = str(payload.get("result", ""))
            first_line = result.split("\n")[0][:120]
            print(f"{_DIM}  {first_line}{_RESET}")
    return on_event


def _make_approver():
    """Return a Policy approver(call, reason) -> bool that prompts the human."""
    def approver(call: dict, reason: str) -> bool:
        print(f"\n{_RED}{_BOLD}approve {_summarize_call(call)}?{_RESET} [y/N] ", end="", flush=True)
        try:
            answer = input().strip().lower()
        except EOFError:
            answer = ""
        return answer in ("y", "yes")
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
    ap.add_argument("serve", nargs="?", help="launch the web UI (python3 -m panda serve)")
    args = ap.parse_args(argv)

    # ── serve sub-command ─────────────────────────────────────────────────
    if args.serve == "serve":
        from .server import main as _serve
        _serve()
        return

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
        harness.run(args.prompt)
        sys.exit(0)

    # ── Interactive REPL ──────────────────────────────────────────────────
    mode_label = args.mode or "safe"
    print(f"{_BOLD}panda{_RESET}  model={harness.model}  mode={mode_label}  jail={harness.workdir}")
    print("Ctrl-D or /exit to quit · Ctrl-C to interrupt a run (session log is preserved)")
    print("/help for commands\n")

    _interrupted = False

    def _handle_sigint(sig, frame):
        nonlocal _interrupted
        _interrupted = True

    signal.signal(signal.SIGINT, _handle_sigint)

    while True:
        try:
            task = input(f"{_CYAN}{_BOLD}panda>{_RESET} ").strip()
        except EOFError:
            print()
            break
        if not task:
            continue

        if task in ("/exit", "/quit"):
            break
        if task == "/help":
            print(textwrap.dedent("""\
                /model [name]  view or change the model (haiku, sonnet, opus, fable, or any model id)
                /clear         reset the conversation and start a new session
                /exit, /quit   quit panda"""))
            continue
        if task == "/clear":
            harness.messages = []
            harness.session_path = None
            print("conversation cleared")
            continue
        if task == "/model":
            print(harness.model)
            continue
        if task.startswith("/model "):
            name = task[len("/model "):].strip()
            harness.model = _MODEL_ALIASES.get(name, name)
            print(f"model set to {harness.model}")
            continue

        _interrupted = False
        try:
            harness.run(task)
        except KeyboardInterrupt:
            _interrupted = True
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue

        if _interrupted:
            path = harness.session_path or "unknown"
            print(f"\n[interrupted — session log is safe; use --resume to continue: {path}]")
        else:
            print()
