"""
Day 1 – Provider
Teaches : wrapping a remote LLM API in a thin, retry-safe HTTP layer.
Design  : pure stdlib; one public entry-point (complete); HTTP isolated in _post;
          neutral message format decouples callers from the Anthropic wire format.
"""
import json, os, time, urllib.error, urllib.request

API_ROOT      = "https://api.anthropic.com/"
DEFAULT_MODEL = "claude-opus-4-6"


def api_key() -> str:
    """Return PANDA_API_KEY → CLAUDE_API_KEY; raise RuntimeError when absent."""
    k = os.environ.get("PANDA_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not k:
        raise RuntimeError(
            "No API key found. Set PANDA_API_KEY or CLAUDE_API_KEY "
            "(e.g. source panda-key.sh)."
        )
    return k


def complete(model: str, system: str, messages: list[dict],
             tools: list[dict] | None = None) -> dict:
    """Call the model; return {text, tool_calls, usage}.
    tools is a list of {"schema":...}; parameters maps to Anthropic input_schema.
    """
    hdrs = {"Content-Type": "application/json",
            "x-api-key": api_key(), "anthropic-version": "2023-06-01"}
    body: dict = {
        "model": model, "max_tokens": 65536, "temperature": 0.4,
        "system": system, "messages": _to_wire(messages),
    }
    if tools:
        body["tools"] = [
            {"name": t["schema"]["name"],
             "description": t["schema"].get("description", ""),
             "input_schema": t["schema"].get("parameters", {"type": "object"})}
            for t in tools
        ]

    raw = _post(f"{API_ROOT}v1/messages", body, headers=hdrs)
    texts, calls = [], []
    for block in raw.get("content", []):
        if block["type"] == "text":
            texts.append(block["text"])
        elif block["type"] == "tool_use":
            calls.append({"name": block["name"], "args": block["input"],
                          "signature": block["id"]})  # id round-trips as signature
    usage = raw.get("usage", {})
    return {"text": "".join(texts), "tool_calls": calls,
            "usage": {"input": usage.get("input_tokens", 0),
                      "output": usage.get("output_tokens", 0)}}


def _to_wire(messages: list[dict]) -> list[dict]:
    """Map neutral dicts to Anthropic wire format.
    user→text content; assistant→text+tool_use blocks (signature=tool_use id);
    tool→grouped tool_result blocks with id recovered from prior assistant msg.
    """
    wire, i = [], 0
    while i < len(messages):
        m = messages[i]
        if m["role"] == "user":
            wire.append({"role": "user", "content": [{"type": "text", "text": m["text"]}]})
            i += 1
        elif m["role"] == "assistant":
            content: list[dict] = []
            if m.get("text"):
                content.append({"type": "text", "text": m["text"]})
            for c in m.get("tool_calls", []):
                content.append({"type": "tool_use",
                                 "id": c.get("signature", c["name"]),
                                 "name": c["name"], "input": c["args"]})
            wire.append({"role": "assistant", "content": content})
            i += 1
        elif m["role"] == "tool":
            # Rebuild ordered (name, id) list from the preceding assistant turn.
            # Must use position-based matching, not name-based, because the same
            # tool can be called multiple times in one turn (parallel tool calls).
            call_ids: list[tuple] = []
            for prev in reversed(messages[:i]):
                if prev["role"] == "assistant":
                    call_ids = [(c["name"], c.get("signature", c["name"]))
                                for c in prev.get("tool_calls", [])]
                    break
            results: list[dict] = []
            pos = 0
            while i < len(messages) and messages[i]["role"] == "tool":
                t = messages[i]; i += 1
                tid = call_ids[pos][1] if pos < len(call_ids) else t["name"]
                pos += 1
                results.append({"type": "tool_result",
                                 "tool_use_id": tid,
                                 "content": t["text"]})
            wire.append({"role": "user", "content": results})
    return wire


def _post(url: str, body: dict, retries: int = 5,
          headers: dict | None = None) -> dict:
    """POST JSON to url with exponential back-off on 429/5xx and network errors.
    Sleeps 2**attempt * 2 s; raises RuntimeError on non-retryable or exhaustion.
    """
    h = dict(headers) if headers else {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=h, method="POST")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503):
                time.sleep(2 ** attempt * 2); continue
            raise RuntimeError(
                f"HTTP {exc.code}: {exc.read(400).decode(errors='replace')}"
            ) from exc
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"Failed after {retries} retries: {url}")
