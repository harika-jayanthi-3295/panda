from __future__ import annotations
from typing import Any, Callable
from . import provider


def run_loop(
    model: str,
    system: str,
    messages: list[dict],
    tools: dict,
    on_event: Callable[[str, Any], None],
    before_tool: Callable[[dict], str | None],
    max_turns: int = 80,
    before_turn: Callable[[list[dict]], list[dict]] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> str:
    """Drive model→tool turns until the model replies with no tool calls.

    messages is mutated in place so the caller retains full history.
    tools    maps name → Tool (.spec dict + .run callable).
    on_event fires: ("assistant", reply), ("tool_start", call),
                    ("tool_end", {call, result}).
    before_tool  returns None to allow a call, or a reason string to block it;
                 blocked calls are recorded as "BLOCKED: <reason>".
    before_turn  optional context-compaction hook, called before each model turn.
    max_turns    safety ceiling; on exhaustion one final no-tool call wraps up.
    should_stop  optional callback to check if loop should stop early.
    """
    specs = [t.spec for t in tools.values()]

    for _ in range(max_turns):
        if should_stop and should_stop():
            return "Session stopped by user."

        if before_turn is not None:
            messages[:] = before_turn(messages)

        reply = provider.complete(model, system, messages, specs)
        messages.append({"role": "assistant", "text": reply["text"],
                         "tool_calls": reply["tool_calls"]})
        on_event("assistant", reply)

        if not reply["tool_calls"]:
            return reply["text"]

        for call in reply["tool_calls"]:
            on_event("tool_start", call)
            reason = before_tool(call)
            if reason is not None:
                result: Any = f"BLOCKED: {reason}"
            elif call["name"] not in tools:
                result = f"ERROR: unknown tool {call['name']}"   # let model recover
            else:
                try:
                    result = tools[call["name"]].run(**call["args"])
                except Exception as exc:
                    result = f"ERROR: {type(exc).__name__}: {exc}"  # never crash loop
            on_event("tool_end", {"call": call, "result": result})
            messages.append({"role": "tool", "name": call["name"], "text": str(result)})

    # Turn limit: append sentinel, make one final no-tool call, return its text.
    messages.append({"role": "user", "text": "Turn limit reached; wrap up now."})
    if before_turn is not None:
        messages[:] = before_turn(messages)
    reply = provider.complete(model, system, messages, [])
    messages.append({"role": "assistant", "text": reply["text"],
                     "tool_calls": reply["tool_calls"]})
    return reply["text"]
