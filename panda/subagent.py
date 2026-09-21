"""
Day 4 – Sub-agent
Teaches : recursive delegation — a tool that launches a fresh child Harness
          so the parent can decompose tasks without sharing its context.
Design  : make_harness is injected by Harness so this module stays free of
          a Harness import, avoiding a circular dependency. max_depth caps
          recursion before the stack blows up.
"""
from .tools import tool


def subagent_tool(make_harness, depth: int = 0, max_depth: int = 2):
    """Return a spawn_agent Tool that delegates work to a fresh child Harness.

    make_harness(depth) must return a configured Harness ready to run.
    """
    @tool(
        "Delegate a self-contained task to a fresh sub-agent with its own clean "
        "context. The child cannot see this conversation and returns its final "
        "report. Use for independent sub-tasks that do not need shared history.",
        task="the complete, standalone task description for the child agent",
    )
    def spawn_agent(task: str) -> str:
        if depth >= max_depth:
            return "ERROR: sub-agent depth limit reached; do this task yourself"
        return make_harness(depth + 1).run(task)

    return spawn_agent
