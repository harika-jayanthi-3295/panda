"""
Day 3 – Context engine
Teaches : token-budget compaction to keep long conversations inside the model window.
Design  : estimate_tokens uses a char-count heuristic; compact summarises old turns
          with one model call and splices the summary before the KEEP_RECENT slice.
"""
from . import provider

CHARS_PER_TOKEN = 4
KEEP_RECENT     = 6

# Prompt for the model when acting as a transcript compressor.
_SYSTEM = (
    "You compress agent transcripts. Preserve: the original task, every file "
    "created or edited and its purpose, key decisions, unresolved errors, and "
    "what remains to be done. Be dense and factual."
)


def estimate_tokens(messages: list[dict]) -> int:
    """Cheap heuristic: sum of str(message) lengths divided by CHARS_PER_TOKEN."""
    return sum(len(str(m)) for m in messages) // CHARS_PER_TOKEN


def compact(model: str, messages: list[dict], budget_tokens: int) -> list[dict]:
    """Return messages shortened to fit within budget_tokens.
    Unchanged when within budget or len ≤ KEEP_RECENT+1. Otherwise summarises
    old turns via one model call, prepending the summary before recent slice.
    """
    if estimate_tokens(messages) <= budget_tokens or len(messages) <= KEEP_RECENT + 1:
        return messages

    old, recent = messages[:-KEEP_RECENT], list(messages[-KEEP_RECENT:])

    # Orphaned result guard: provider rejects a conversation starting with tool.
    while recent and recent[0]["role"] == "tool":
        recent.pop(0)

    lines = []
    for m in old:
        role = m["role"]
        if role == "tool":
            lines.append(f"tool({m.get('name', '?')}): {str(m.get('text', ''))[:200]}")
        elif role == "assistant":
            txt   = str(m.get("text", ""))[:200]
            calls = ", ".join(c["name"] for c in m.get("tool_calls", []))
            lines.append(f"assistant: {txt}" + (f" [calls: {calls}]" if calls else ""))
        else:
            lines.append(f"{role}: {str(m.get('text', ''))[:200]}")

    reply = provider.complete(
        model, _SYSTEM, [{"role": "user", "text": "\n".join(lines)}]
    )
    return [{"role": "user",
             "text": f"[Conversation so far, compacted]\n{reply['text']}"}] + recent
