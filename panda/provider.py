"""
Day 1 – Provider
Teaches : wrapping a remote LLM API in a thin, retry-safe HTTP layer.
Design  : pure stdlib; one public entry-point (complete); HTTP isolated in _post;
          neutral message format decouples callers from the wire format.
"""
import json, os, time, urllib.error, urllib.request

API_ROOT      = "https://generativelanguage.googleapis.com/"
DEFAULT_MODEL = "claude-opus-4-6"


def api_key() -> str:
    """Return PANDA_API_KEY, falling back to CLAUDE_API_KEY.
    Raises RuntimeError so the error surfaces before any HTTP call is made.
    """
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

    tools is a list of {"schema": ...} dicts passed as functionDeclarations.
    """
    url = f"{API_ROOT}v1beta/models/{model}:generateContent?key={api_key()}"
    body: dict = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents"         : _to_wire(messages),
        "generationConfig" : {"temperature": 0.4, "maxOutputTokens": 65536},
    }
    if tools:
        body["tools"] = [{"functionDeclarations": [t["schema"] for t in tools]}]

    raw   = _post(url, body)
    parts = raw["candidates"][0]["content"].get("parts", [])
    meta  = raw.get("usageMetadata", {})
    texts, calls = [], []
    for p in parts:
        if p.get("thought"):            # skip internal reasoning traces
            continue
        if "text" in p:
            texts.append(p["text"])
        if "functionCall" in p:
            fc = p["functionCall"]
            calls.append({
                "name"     : fc["name"],
                "args"     : fc.get("args", {}),
                # thoughtSignature is on the outer part; must echo back (Gemini 3 rule).
                "signature": p.get("thoughtSignature"),
            })
    return {
        "text"      : "".join(texts),
        "tool_calls": calls,
        "usage"     : {"input" : meta.get("promptTokenCount", 0),
                       "output": meta.get("candidatesTokenCount", 0)},
    }


def _to_wire(messages: list[dict]) -> list[dict]:
    """Map neutral message dicts to Gemini wire format.

    user      → role "user"  with a text part
    assistant → role "model" with text part (if any) + functionCall parts;
                each functionCall echoes stored signature as thoughtSignature
    tool      → role "user"  with a functionResponse part
    """
    wire = []
    for m in messages:
        if m["role"] == "user":
            wire.append({"role": "user", "parts": [{"text": m["text"]}]})
        elif m["role"] == "assistant":
            parts: list[dict] = []
            if m.get("text"):
                parts.append({"text": m["text"]})
            for c in m.get("tool_calls", []):
                part: dict = {"functionCall": {"name": c["name"], "args": c["args"]}}
                if c.get("signature"):
                    part["thoughtSignature"] = c["signature"]   # required round-trip
                parts.append(part)
            wire.append({"role": "model", "parts": parts})
        elif m["role"] == "tool":
            wire.append({"role": "user", "parts": [{
                "functionResponse": {"name": m["name"],
                                     "response": {"result": m["text"]}},
            }]})
    return wire


def _post(url: str, body: dict, retries: int = 5) -> dict:
    """POST JSON to url with exponential back-off on 429/5xx and network errors.
    Sleeps 2**attempt * 2 s; raises RuntimeError on non-retryable or exhaustion.
    """
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
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
