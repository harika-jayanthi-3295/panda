"""
Day 1 – Dice demo
Teaches : wiring a hand-written tool into the agent loop end-to-end.
Design  : the simplest possible tool object (spec + run) proves that the
          loop needs nothing else from a tool.
"""
import random, sys, os

# Make the package importable when run directly from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panda import loop, provider


class RollDiceTool:
    """Six-sided dice roller – the Hello World of agent tools."""

    spec = {
        "schema": {
            "name"       : "roll_dice",
            "description": "Roll count six-sided dice",
            "parameters" : {
                "type"      : "object",
                "properties": {"count": {"type": "string",
                                         "description": "How many dice"}},
                "required"  : ["count"],
            },
        }
    }

    def run(self, count: str) -> list[int]:
        """Roll *count* six-sided dice and return the individual results."""
        return [random.randint(1, 6) for _ in range(int(count))]


def on_event(kind: str, payload) -> None:
    """Print every loop event so the full transcript appears in the terminal."""
    if kind == "assistant":
        if payload["text"]:
            print(f"\n[assistant] {payload['text']}")
        for c in payload["tool_calls"]:
            print(f"\n[assistant → tool_call] {c['name']}({c['args']})")
    elif kind == "tool_start":
        print(f"[tool_start] {payload['name']}({payload['args']})")
    elif kind == "tool_end":
        print(f"[tool_end]   result = {payload['result']}")


def before_tool(call: dict):
    """Always allow – no confirmation needed in this demo."""
    return None


def run_demo(title: str, messages: list[dict], tools: dict) -> str:
    """Run one demo task and return the model answer."""
    print("=" * 60)
    print(f"DEMO – {title}")
    print("=" * 60)
    answer = loop.run_loop(
        model      = provider.DEFAULT_MODEL,
        system     = "You are a helpful assistant.",
        messages   = messages,
        tools      = tools,
        on_event   = on_event,
        before_tool= before_tool,
    )
    print(f"\n[final answer]\n{answer[:400]}\n")
    return answer


if __name__ == "__main__":
    # Demo 1 – dice task: expect tool_call → tool result → text answer
    run_demo(
        "Roll 3 dice",
        messages=[{"role": "user",
                   "text": "Roll 3 dice and tell me whether the total beats 10."}],
        tools={"roll_dice": RollDiceTool()},
    )

    # Demo 2 – no-tool task: expect only a text answer, no tool calls
    run_demo(
        "Build a landing page for a coffee shop",
        messages=[{"role": "user",
                   "text": "Build a landing page for a coffee shop."}],
        tools={},
    )
