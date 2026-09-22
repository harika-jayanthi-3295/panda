"""Wiki storage with the model as its editor.

save() routes a new fact to CREATE / UPDATE / LINK, then has the model rewrite
the target entry so the wiki stays a synthesis instead of a changelog. Keyword
overlap only narrows the candidates — the routing and merging judgements are
the model's, because word overlap cannot tell that "auth token refresh bug"
and "session expiry regression" are the same subject. With no API key, or on
any model error, every step degrades to the mechanical append this module used
to do, so the wiki still works offline.
"""
import os, pathlib, re, time

from . import provider

WIKI_DIR    = "wiki"
HISTORY_DIR = ".history"
TAU_DUP     = 0.9    # at/above: same subject, don't spend a call asking
TAU_UPDATE  = 0.5    # fallback threshold when no model is reachable
TAU_LINK    = 0.25   # at/above: cross-link the two entries
MAX_CANDIDATES = 5
MAX_WORDS      = 300  # hard cap; the prompts ask for 250
CONFIDENCE     = ("high", "medium", "low")

_ROUTE_SYS = (
    "You route a new fact into an encyclopedia. Reply with exactly one line:\n"
    "CREATE — no candidate is about the same subject\n"
    "UPDATE <slug> — that candidate's subject should absorb this fact\n"
    "LINK <slug> — related but a distinct subject, so create a cross-linked entry\n"
    "Judge by subject, not by shared vocabulary. No explanation."
)

_MERGE_SYS = (
    "You maintain one encyclopedia entry. Rewrite it so it absorbs the new fact: "
    "no duplicated claims, no changelog voice, no 'Update:' paragraphs. "
    "Keep every source marker [sN] attached to the claim it supports, and tag "
    "claims the new fact contributes with its marker. "
    "Record only what the sources state or directly imply. Never add background "
    "knowledge, rationale, or detail of your own — this is a record, not an essay.\n"
    "CONFLICT means the two claims cannot both be true. A fact that merely adds "
    "detail, scope, or a new symptom is not a conflict — merge it as OK. "
    "On a real conflict keep both readings under a '## Contradictions' heading "
    "with their markers, and never silently overwrite the older one.\n"
    "Reply with a status word on line 1, then the body:\n"
    "OK — rewritten body follows\n"
    "CONFLICT — rewritten body follows and records a contradiction\n"
    "UNCHANGED — the entry already covers this; write nothing after line 1\n"
    "Body is markdown only, under 250 words, no frontmatter, no code fences "
    "around the whole answer."
)

_CREATE_SYS = (
    "Write a new encyclopedia entry for the fact given. Reply exactly:\n"
    "TITLE: <canonical noun-phrase title, under 60 characters>\n"
    "SUMMARY: <one line, under 120 characters>\n"
    "\n"
    "<body markdown, under 250 words, keeping the [sN] source marker>\n"
    "The title is how this entry gets found again — name the subject, not the "
    "sentence. Record only what the fact states or directly implies: no invented "
    "rationale, no background knowledge, no headings the fact does not support. "
    "A one-line fact makes a one-line entry. "
    "No frontmatter, no code fences around the whole answer."
)


# ------------------------------------------------------------- text helpers

def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (s or "entry")[:40]


def _wiki_root(workdir: str) -> pathlib.Path:
    root = pathlib.Path(workdir) / WIKI_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


# ------------------------------------------------------------ entry storage

def _parse_sources(raw: str) -> list[dict]:
    """Read 's1=src/auth.py@2026-01-01' items; bare refs are legacy entries."""
    out = []
    for i, item in enumerate((s.strip() for s in raw.split(",")), 1):
        if not item:
            continue
        sid, _, rest = item.partition("=")
        if not rest:                      # legacy: 'sources: add.py'
            sid, rest = f"s{i}", item
        ref, _, added = rest.partition("@")
        out.append({"id": sid, "ref": ref, "added": added})
    return out


def _fmt_sources(sources: list[dict]) -> str:
    return ", ".join(f"{s['id']}={s['ref']}@{s['added']}" for s in sources)


def _parse(path: pathlib.Path) -> dict:
    """Split a wiki file into its frontmatter fields plus body."""
    text = path.read_text()
    _, _, rest = text.partition("---\n")
    front, _, body = rest.partition("\n---\n")
    meta: dict = {"sources": [], "links": [], "summary": "", "confidence": "medium"}
    for line in front.splitlines():
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "sources":
            meta["sources"] = _parse_sources(val)
        elif key == "links":
            meta["links"] = [v.strip() for v in val.split(",") if v.strip()]
        elif key:
            meta[key] = val
    if meta.get("confidence") not in CONFIDENCE:
        meta["confidence"] = "medium"
    meta["body"] = body.strip()
    meta["slug"] = path.stem
    return meta


def _render(meta: dict) -> str:
    return "\n".join([
        "---",
        f"title: {meta['title']}",
        f"summary: {meta.get('summary', '')}",
        f"confidence: {meta.get('confidence', 'medium')}",
        f"sources: {_fmt_sources(meta['sources'])}",
        f"links: {', '.join(meta['links'])}",
        f"created: {meta['created']}",
        f"updated: {meta['updated']}",
        "---",
        meta["body"].strip(),
        "",
    ])


def _write(root: pathlib.Path, meta: dict) -> None:
    """Snapshot the previous version, then replace the file atomically.

    Merges rewrite text the agent can no longer recover from context, so every
    overwrite leaves the prior copy under wiki/.history/<slug>/.
    """
    path = root / f"{meta['slug']}.md"
    if path.exists():
        hist = root / HISTORY_DIR / meta["slug"]
        hist.mkdir(parents=True, exist_ok=True)
        (hist / f"{time.strftime('%Y%m%dT%H%M%S')}.md").write_text(path.read_text())
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(_render(meta))
    os.replace(tmp, path)


def _all_entries(workdir: str) -> list[dict]:
    """Every entry at the wiki root — .history/ lives a level down, so it's skipped."""
    return [_parse(p) for p in sorted(_wiki_root(workdir).glob("*.md"))]


def _next_source(sources: list[dict], ref: str) -> tuple[list[dict], str]:
    """Return (sources, marker) — reusing the marker when this ref is already cited."""
    for s in sources:
        if s["ref"] == ref:
            return sources, s["id"]
    used = {s["id"] for s in sources}
    n = len(sources) + 1
    while f"s{n}" in used:
        n += 1
    sid = f"s{n}"
    return sources + [{"id": sid, "ref": ref,
                       "added": time.strftime("%Y-%m-%dT%H:%M:%S")}], sid


# ---------------------------------------------------------------- the model

def _ask(model: str | None, system: str, prompt: str, llm=None) -> str | None:
    """Return the model's text, or None when no model is reachable.

    None is the signal to fall back to mechanical behaviour — callers must
    never treat an unreachable model as a reason to lose the fact.
    """
    if llm is not None:
        return llm(system, prompt)
    try:
        provider.api_key()
        out = provider.complete(model or provider.DEFAULT_MODEL, system,
                                [{"role": "user", "text": prompt}])
    except (RuntimeError, OSError):
        return None
    return (out.get("text") or "").strip() or None


def _clean(text: str) -> str:
    """Drop a wrapping code fence and any frontmatter the model invented."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t.strip())
    if t.startswith("---"):
        _, _, after = t.partition("---\n")
        _, sep, body = after.partition("\n---\n")
        t = body if sep else after
    return t.strip()


_CONTRA = re.compile(r"^##\s*contradictions\s*$(.*?)(?=^##\s|\Z)", re.M | re.I | re.S)


def _contradictions(body: str) -> str:
    m = _CONTRA.search(body)
    return " ".join(m.group(1).split()) if m else ""


def _recorded_conflict(old: str, new: str) -> bool:
    """True when the rewrite added or changed a ## Contradictions section.

    The model's status word is advisory — it will happily write a
    contradiction into the body and still label the merge OK. The section
    itself is the fact, so that is what we check.
    """
    new_c = _contradictions(new)
    return bool(new_c) and new_c != _contradictions(old)


def _validate(body: str, source_ids: set[str]) -> str:
    """Return '' when the body is fit to write, else the reason it is not."""
    if not body.strip():
        return "body is empty"
    words = len(body.split())
    if words > MAX_WORDS:
        return f"body is {words} words, over the {MAX_WORDS}-word cap"
    unknown = {m for m in re.findall(r"\[(s\d+)\]", body)} - source_ids
    if unknown:
        return f"body cites unknown source markers: {', '.join(sorted(unknown))}"
    return ""


def _ask_valid(model, system: str, prompt: str, llm, source_ids: set[str]):
    """Ask, validate, and give the model exactly one chance to repair itself."""
    raw = _ask(model, system, prompt, llm)
    if raw is None:
        return None
    status, _, body = raw.partition("\n")
    status, body = status.strip().upper(), _clean(body)
    if status == "UNCHANGED":
        return status, ""
    err = _validate(body, source_ids)
    if err:
        raw = _ask(model, system, f"{prompt}\n\nYour last answer was rejected: "
                                  f"{err}. Return a corrected answer.", llm)
        if raw is None:
            return None
        status, _, body = raw.partition("\n")
        status, body = status.strip().upper(), _clean(body)
        if status != "UNCHANGED" and _validate(body, source_ids):
            return None
    return status, body


# ---------------------------------------------------------------- behaviour

def _candidates(entries: list[dict], tokens: set[str]) -> list[tuple[float, dict]]:
    """Rank every entry by overlap. Zero-overlap entries stay on the list —
    overlap only orders the menu, it does not get to veto a subject match."""
    scored = [(_jaccard(tokens, _tokenize(f"{e['title']} {e['summary']} {e['body']}")), e)
              for e in entries]
    return sorted(scored, key=lambda s: -s[0])


def _route(model, llm, title: str, fact: str,
           ranked: list[tuple[float, dict]]) -> tuple[str, dict | None]:
    """Decide CREATE / UPDATE / LINK. Overlap narrows; the model judges."""
    if not ranked:                                   # empty wiki
        return "CREATE", None
    slug = _slug(title)
    for _, e in ranked:                              # same canonical title
        if e["slug"] == slug:
            return "UPDATE", e
    if ranked[0][0] >= TAU_DUP:                      # same subject, don't ask
        return "UPDATE", ranked[0][1]

    top   = ranked[:MAX_CANDIDATES]
    menu  = "\n".join(f"- {e['slug']}: {e['title']} — "
                      f"{e['summary'] or e['body'][:150]}" for _, e in top)
    reply = _ask(model, _ROUTE_SYS,
                 f"New fact titled {title!r}:\n{fact}\n\nCandidates:\n{menu}", llm)
    if reply:
        parts = reply.split()
        action = parts[0].upper().strip(":")
        slug   = parts[1].strip("<>`") if len(parts) > 1 else ""
        byslug = {e["slug"]: e for _, e in top}
        if action == "CREATE":
            return "CREATE", None
        if action in ("UPDATE", "LINK") and slug in byslug:
            return action, byslug[slug]
    # Unreachable or unusable answer: fall back to the old threshold rule.
    best_sim, best = ranked[0]
    return ("UPDATE", best) if best_sim >= TAU_UPDATE else ("CREATE", None)


def _links_for(tokens: set[str], entries: list[dict], exclude: str) -> list[str]:
    return [e["slug"] for e in entries
            if e["slug"] != exclude
            and _jaccard(tokens, _tokenize(f"{e['title']} {e['body']}")) >= TAU_LINK]


def _backlink(root: pathlib.Path, entries: list[dict], links: list[str], slug: str) -> None:
    for e in entries:
        if e["slug"] in links and slug not in e["links"]:
            e["links"].append(slug)
            _write(root, e)


def save(workdir: str, title: str, body: str, source: str = "conversation",
         model: str | None = None, llm=None) -> str:
    """Route a fact into the wiki and let the model write the markdown.

    llm is an optional (system, prompt) -> str callable, injected by tests.
    """
    root    = _wiki_root(workdir)
    entries = _all_entries(workdir)
    tokens  = _tokenize(f"{title} {body}")
    now     = time.strftime("%Y-%m-%dT%H:%M:%S")

    action, target = _route(model, llm, title, body, _candidates(entries, tokens))

    if action == "UPDATE" and target is not None:
        sources, marker = _next_source(target["sources"], source)
        prompt = (f"Entry title: {target['title']}\n"
                  f"Sources: {_fmt_sources(sources)}\n\n"
                  f"Current body:\n{target['body']}\n\n"
                  f"New fact (cite it as [{marker}]):\n{body}")
        result = _ask_valid(model, _MERGE_SYS, prompt, llm, {s["id"] for s in sources})

        if result is None:                    # offline or unusable: never lose it
            target["body"] += f"\n\nUpdate ({now}) [{marker}]: {body.strip()}"
            note = " [no model: appended without merge]"
            status = "OK"
        else:
            status, merged = result
            note = ""
            if status != "UNCHANGED":
                if merged.strip() == target["body"].strip():
                    status = "UNCHANGED"          # rewrote it to the same text
                else:
                    if _recorded_conflict(target["body"], merged):
                        status = "CONFLICT"
                    target["body"] = merged
        if status == "CONFLICT":
            target["confidence"] = "low"
        target["sources"] = sources
        target["updated"] = now
        peers = [e for e in entries if e["slug"] != target["slug"]]
        for slug in _links_for(_tokenize(f"{target['title']} {target['body']}"),
                               peers, target["slug"]):
            if slug not in target["links"]:
                target["links"].append(slug)
        _write(root, target)
        _backlink(root, peers, target["links"], target["slug"])

        if status == "CONFLICT":
            return (f"CONFLICT in {target['slug']}.md: the new fact contradicts "
                    f"'{target['title']}' — both readings kept under "
                    f"## Contradictions, confidence lowered to low. Resolve it.")
        if status == "UNCHANGED":
            return (f"No change: '{target['title']}' ({target['slug']}.md) already "
                    f"covers this; recorded {source} as {marker}.")
        return f"Updated wiki entry '{target['title']}' ({target['slug']}.md){note}"

    # CREATE (optionally forced to cross-link the entry the router named)
    sources, marker = _next_source([], source)
    new_title, summary, new_body = title, "", body.strip()
    written = _ask(model, _CREATE_SYS,
                   f"Title hint: {title}\nSource marker: [{marker}] ({source})\n"
                   f"Fact:\n{body}", llm)
    if written:
        text = _clean(written)
        m_t = re.search(r"^TITLE:\s*(.+)$", text, re.M)
        m_s = re.search(r"^SUMMARY:\s*(.+)$", text, re.M)
        drafted = re.sub(r"^(TITLE|SUMMARY):.*$", "", text, flags=re.M).strip()
        if m_t and not _validate(drafted, {marker}):
            new_title = m_t.group(1).strip()
            summary   = m_s.group(1).strip() if m_s else ""
            new_body  = drafted
    if not summary:
        summary = re.split(r"(?<=[.!?])\s", new_body.strip())[0][:120]

    slug = _slug(new_title)
    if (root / f"{slug}.md").exists():
        slug = f"{slug}-{int(time.time())}"
    links = _links_for(_tokenize(f"{new_title} {new_body}"), entries, slug)
    if action == "LINK" and target is not None and target["slug"] not in links:
        links.append(target["slug"])

    meta = {"title": new_title, "summary": summary, "confidence": "medium",
            "sources": sources, "links": links, "created": now, "updated": now,
            "body": new_body, "slug": slug}
    _write(root, meta)
    _backlink(root, entries, links, slug)

    note   = "" if written else " [no model: fact stored verbatim]"
    linked = f"; linked to {', '.join(links)}" if links else ""
    return f"Created wiki entry '{new_title}' ({slug}.md){linked}{note}"


def _best_section(body: str, tokens: set[str], cap: int = 800) -> str:
    """Return the '## ' section that best matches the query, capped in size."""
    if len(body) <= cap:
        return body
    chunks = re.split(r"\n(?=##\s)", body)
    best   = max(chunks, key=lambda c: _jaccard(tokens, _tokenize(c)))
    return best[:cap] + ("…" if len(best) > cap else "")


def query(workdir: str, question: str, top_k: int = 3) -> str:
    """Return the entries most relevant to question, trimmed to what matched."""
    tokens  = _tokenize(question)
    entries = _all_entries(workdir)
    byslug  = {e["slug"]: e for e in entries}
    # Score the label and the prose separately and keep the better of the two:
    # a long body otherwise drowns a direct title hit in its own token count.
    scored  = [(max(_jaccard(tokens, _tokenize(f"{e['title']} {e['summary']}")),
                    _jaccard(tokens, _tokenize(e["body"]))), e)
               for e in entries]
    scored  = sorted((s for s in scored if s[0] > 0), key=lambda s: -s[0])[:top_k]
    if not scored:
        return "No wiki entries matched."
    parts = []
    for sim, e in scored:
        head = f"## {e['title']} (match {sim:.2f}, confidence {e['confidence']})"
        if e["summary"]:
            head += f"\n{e['summary']}"
        body = _best_section(e["body"], tokens)
        seealso = ", ".join(f"{byslug[s]['title']} [{s}]" if s in byslug else s
                            for s in e["links"])
        cites = ", ".join(f"{s['id']}={s['ref']}" for s in e["sources"])
        tail  = "\n".join(filter(None, [
            f"sources: {cites}" if cites else "",
            f"see also: {seealso}" if seealso else "",
        ]))
        parts.append(f"{head}\n{body}\n{tail}".strip())
    return "\n\n".join(parts)
