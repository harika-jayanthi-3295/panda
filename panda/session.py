"""
Day 4 – Session
Teaches : durable conversation persistence with torn-tail repair so a killed
          process can resume where it left off without violating the
          call/response pairing rule the provider requires.
Design  : one .jsonl per session; append is the only write path; load stops
          at the first unparseable line (the torn tail) and calls _repair
          before returning so the caller always gets a valid message list.
"""
import json, pathlib, re, time

SESSION_DIR = ".panda/sessions"


def new_session(workdir: str, label: str = "session") -> str:
    """Create the session directory and return a timestamped .jsonl path.

    The label is slugified to alphanumerics and dashes, clipped to 40 chars.
    """
    slug = re.sub(r"[^a-z0-9-]+", "-", label.lower())[:40].strip("-") or "session"
    d = pathlib.Path(workdir) / SESSION_DIR
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{int(time.time())}-{slug}.jsonl")


def append(path: str, message: dict) -> None:
    """Append one message as a JSON line (ensure_ascii=False for unicode)."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")


def load(path: str) -> list[dict]:
    """Load messages; stop at first unparseable line (torn tail) then repair."""
    messages: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    break          # torn tail — discard remainder
    except FileNotFoundError:
        return []
    return _repair(messages)


def latest(workdir: str) -> str | None:
    """Return the newest .jsonl path in the session dir, or None."""
    d = pathlib.Path(workdir) / SESSION_DIR
    files = sorted(d.glob("*.jsonl")) if d.is_dir() else []
    return str(files[-1]) if files else None


def _repair(messages: list[dict]) -> list[dict]:
    """Ensure every tool_call in the last assistant message has a matching result.

    Finds the last assistant message; any tool_calls beyond the count of
    following tool messages get a synthetic "Interrupted" result appended.
    Restores the call/response pairing the provider requires after a crash.
    """
    last_asst = next(
        (i for i in range(len(messages) - 1, -1, -1)
         if messages[i]["role"] == "assistant"), None
    )
    if last_asst is None:
        return messages
    tool_after = sum(1 for m in messages[last_asst + 1:] if m["role"] == "tool")
    for call in messages[last_asst].get("tool_calls", [])[tool_after:]:
        messages.append({
            "role": "tool", "name": call["name"],
            "text": "Interrupted before this ran (process restarted).",
        })
    return messages
