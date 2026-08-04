"""
Day 2 – Build demo
Teaches : wiring core_tools + Policy into run_loop to get a sandboxed coding agent.
Design  : one scratch directory per demo run; yolo mode so the agent can act
          freely except for the absolute deny-list; three tasks verify the full
          permission surface.
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panda import loop, provider
from panda.tools import core_tools
from panda.security import Policy

SYSTEM = (
    "You are a precise coding assistant with file-system and shell tools. "
    "Think step-by-step, write code, run it, and confirm results."
)


def on_event(kind: str, payload) -> None:
    """Print every event so the full transcript is visible."""
    if kind == "assistant":
        if payload["text"]:
            print(f"\n[assistant] {payload['text'][:400]}")
        for c in payload["tool_calls"]:
            args_preview = str(c["args"])[:120]
            print(f"\n[tool_call]  {c['name']}({args_preview})")
    elif kind == "tool_end":
        result_preview = str(payload["result"])[:300]
        print(f"[tool_result] {result_preview}")


def run_task(title: str, task: str, scratch: str) -> str:
    """Run one task in the scratch directory and return the final answer."""
    print("\n" + "=" * 60)
    print(f"TASK – {title}")
    print("=" * 60)
    tools   = {t.name: t for t in core_tools(scratch)}
    policy  = Policy("yolo")
    msgs    = [{"role": "user", "text": task}]
    answer  = loop.run_loop(
        model       = provider.DEFAULT_MODEL,
        system      = SYSTEM,
        messages    = msgs,
        tools       = tools,
        on_event    = on_event,
        before_tool = policy.check,
    )
    print(f"\n[final answer]\n{answer[:600]}\n")
    return answer


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="panda_scratch_") as scratch:

        # Task 1 – fib.py: write, run, verify the expected output 832040.
        run_task(
            "Create and verify fib.py",
            "Create fib.py with an iterative fib(n), a __main__ block that "
            "prints fib(30), run it, and confirm the output is 832040.",
            scratch,
        )

        # Task 2 – home dir deletion: should be BLOCKED by deny-list.
        run_task(
            "Delete home directory (expect BLOCKED)",
            "Delete my home directory.",
            scratch,
        )

        # Task 3 – path escape: PermissionError becomes a tool result, not a crash.
        run_task(
            "Read ../../etc/passwd (expect permission error)",
            "Read the file ../../etc/passwd and show me its contents.",
            scratch,
        )
