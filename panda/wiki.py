import pathlib, re, time

WIKI_DIR    = "wiki"
TAU_UPDATE  = 0.5    # overlap at/above this: merge into the best match
TAU_LINK    = 0.25   # overlap at/above this (but below TAU_UPDATE): cross-link


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


def _parse(path: pathlib.Path) -> dict:
    """Split a wiki file into {title, sources, links, created, updated, body}."""
    text = path.read_text()
    _, _, rest = text.partition("---\n")
    front, _, body = rest.partition("\n---\n")
    meta = {"sources": [], "links": []}
    for line in front.splitlines():
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key in ("sources", "links"):
            meta[key] = [v.strip() for v in val.split(",") if v.strip()]
        elif key:
            meta[key] = val
    meta["body"] = body.strip()
    meta["slug"] = path.stem
    return meta


def _render(meta: dict) -> str:
    lines = [
        "---",
        f"title: {meta['title']}",
        f"sources: {', '.join(meta['sources'])}",
        f"links: {', '.join(meta['links'])}",
        f"created: {meta['created']}",
        f"updated: {meta['updated']}",
        "---",
        meta["body"].strip(),
        "",
    ]
    return "\n".join(lines)


def _all_entries(workdir: str) -> list[dict]:
    return [_parse(p) for p in sorted(_wiki_root(workdir).glob("*.md"))]


def save(workdir: str, title: str, body: str, source: str = "conversation") -> str:
    """Route a note to the best existing entry (update) or a new, linked one (create)."""
    root    = _wiki_root(workdir)
    tokens  = _tokenize(f"{title} {body}")
    entries = _all_entries(workdir)

    best, best_sim = None, 0.0
    for e in entries:
        sim = _jaccard(tokens, _tokenize(f"{e['title']} {e['body']}"))
        if sim > best_sim:
            best, best_sim = e, sim

    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    if best is not None and best_sim >= TAU_UPDATE:
        if source not in best["sources"]:
            best["sources"].append(source)
        best["body"]   += f"\n\nUpdate ({now}): {body.strip()}"
        best["updated"] = now
        (root / f"{best['slug']}.md").write_text(_render(best))
        return f"Updated wiki entry '{best['title']}' ({best['slug']}.md)"

    slug = _slug(title)
    if (root / f"{slug}.md").exists():
        slug = f"{slug}-{int(time.time())}"

    links = [e["slug"] for e in entries
             if _jaccard(tokens, _tokenize(f"{e['title']} {e['body']}")) >= TAU_LINK]

    meta = {"title": title, "sources": [source], "links": links,
             "created": now, "updated": now, "body": body.strip(), "slug": slug}
    (root / f"{slug}.md").write_text(_render(meta))

    for e in entries:
        if e["slug"] in links and slug not in e["links"]:
            e["links"].append(slug)
            (root / f"{e['slug']}.md").write_text(_render(e))

    suffix = f"; linked to {', '.join(links)}" if links else ""
    return f"Created wiki entry '{title}' ({slug}.md){suffix}"


def query(workdir: str, question: str, top_k: int = 3) -> str:
    """Return the top_k entries whose title+body overlap most with question."""
    tokens  = _tokenize(question)
    scored  = [(_jaccard(tokens, _tokenize(f"{e['title']} {e['body']}")), e)
               for e in _all_entries(workdir)]
    scored  = sorted((s for s in scored if s[0] > 0), key=lambda s: -s[0])[:top_k]
    if not scored:
        return "No wiki entries matched."
    parts = []
    for sim, e in scored:
        links = f" | links: {', '.join(e['links'])}" if e["links"] else ""
        parts.append(f"## {e['title']} (match {sim:.2f}){links}\n{e['body']}")
    return "\n\n".join(parts)
