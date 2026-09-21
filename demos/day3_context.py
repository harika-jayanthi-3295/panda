"""
Day 3 – Context demo
Teaches : wiring compact() into the before_turn hook so the agent can run
          long tasks without overflowing the context window.
Design  : a tight budget_tokens forces compaction early so the behaviour is
          visible without needing a huge task.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panda import loop, provider
from PatchPilot.panda.context import compact, estimate_tokens
from PatchPilot.panda.tools import core_tools
from PatchPilot.panda.security import Policy

BUDGET = 4000   # tight budget so compaction triggers within a few turns


def on_event(kind: str, payload) -> None:
    """Print each event; show message count before every compaction check."""
    if kind == "assistant":
        if payload["text"]:
            print(f"\n[assistant] {payload['text'][:300]}")
        for c in payload["tool_calls"]:
            print(f"\n[tool_call]  {c['name']}({str(c['args'])[:100]})")
    elif kind == "tool_end":
        print(f"[tool_result] {str(payload['result'])[:200]}")


def make_before_turn(model: str):
    """Return a before_turn callback that compacts and reports when it fires."""
    def before_turn(msgs: list[dict]) -> list[dict]:
        tokens_before = estimate_tokens(msgs)
        compacted = compact(model, msgs, BUDGET)
        if len(compacted) < len(msgs):
            print(f"\n[context] compacted {len(msgs)} msgs "
                  f"({tokens_before} tok) → {len(compacted)} msgs")
        return compacted
    return before_turn


if __name__ == "__main__":
    model = provider.DEFAULT_MODEL
    with tempfile.TemporaryDirectory(prefix="panda_day3_") as scratch:
        tools  = {t.name: t for t in core_tools(scratch)}
        policy = Policy("yolo")
        msgs   = [{
            "role": "user",
            "text": (
                "Create utils.py with three functions: add(a,b), multiply(a,b), "
                "and factorial(n). Then create test_utils.py that tests each "
                "function. Run the tests and confirm they all pass."
            ),
        }]

        answer = loop.run_loop(
            model       = model,
            system      = "You are a coding assistant with file and shell tools.",
            messages    = msgs,
            tools       = tools,
            on_event    = on_event,
            before_tool = policy.check,
            before_turn = make_before_turn(model),
        )
        print(f"\n[final answer]\n{answer[:500]}")
        print(f"\n[final history length] {len(msgs)} messages")
