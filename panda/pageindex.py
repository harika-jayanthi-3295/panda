#!/usr/bin/env python3
"""PageIndex — a structural table of contents a model can reason over.

No embeddings, no vector store, no third-party dependencies. The index is a
tree of (id, title, path, line-range, summary, refs) nodes; retrieval is the
model choosing node ids and reading exact line ranges, not cosine similarity.

    python3 -m panda.pageindex build .          # write .panda/pageindex.json
    python3 -m panda.pageindex toc --depth 2    # the map the model reasons over
    python3 -m panda.pageindex search "retry"   # ids whose title/summary match
    python3 -m panda.pageindex read 3.2 7 --budget 6000
    python3 -m panda.pageindex refs 3.2         # outgoing cross-references
"""
import argparse, json, pathlib, re, sys, time

IGNORE   = {".git", "node_modules", "__pycache__", ".venv", ".panda", "dist", "build"}
TEXT_EXT = {".md", ".markdown", ".txt", ".rst", ".py", ".ipynb", ".json", ".yaml",
            ".yml", ".toml", ".cfg", ".ini", ".sh", ".js", ".ts", ".tsx", ".go",
            ".java", ".rb", ".rs", ".sql", ".html", ".css"}
DEFAULT_INDEX = ".panda/pageindex.json"
CHARS_PER_TOK = 4        # rough, but good enough for budgeting reads

MD_HEAD  = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
CELL_MARK = re.compile(r"^<!-- cell \d+ \[(\w+)\] -->$")
PY_DEF   = re.compile(r"^(\s*)(?:async\s+)?(def|class)\s+(\w+)")
REF_PATS = [
    re.compile(r"\[[^\]]*\]\(([^)\s]+)\)"),                                  # md link
    re.compile(r"\b(?:see|refer to|defined in|described in)[ \t]+"
               r"((?:[A-Z][\w-]+)(?:[ \t]+[A-Z][\w-]+){0,2})"),
    re.compile(r"\b((?:Section|Appendix|Chapter|Table|Figure)[ \t]+[A-Z0-9][\w.]*)"),
    re.compile(r"\b[\w/-]+\.(?:py|md|ipynb|txt|json|ya?ml|ts|js|go|rs|sh)\b"),
]


# ---------------------------------------------------------------- flattening

def lines_of(path: pathlib.Path) -> list[str]:
    """Return the file as a line list. Notebooks are flattened deterministically
    so that build-time and read-time line numbers always agree."""
    if path.suffix != ".ipynb":
        return path.read_text(errors="replace").splitlines()
    try:
        nb = json.loads(path.read_text(errors="replace"))
    except json.JSONDecodeError:
        return path.read_text(errors="replace").splitlines()
    out: list[str] = []
    for i, cell in enumerate(nb.get("cells", [])):
        out.append(f"<!-- cell {i} [{cell.get('cell_type', '?')}] -->")
        out.extend("".join(cell.get("source", [])).splitlines())
        out.append("")
    return out


# ------------------------------------------------------------------ outlines

def outline(path: pathlib.Path, lines: list[str]) -> list[tuple[int, str, int]]:
    """Return [(level, title, 0-based line)] headings for one file, or []."""
    suffix = path.suffix
    heads: list[tuple[int, str, int]] = []
    if suffix in (".md", ".markdown", ".ipynb", ".txt", ".rst"):
        fence, prose = False, True
        for n, line in enumerate(lines):
            m_cell = CELL_MARK.match(line)
            if m_cell:                       # notebook: '#' is a heading only
                prose, fence = m_cell.group(1) == "markdown", False
                continue
            if line.lstrip().startswith("```"):
                fence = not fence
            if fence or not prose:           # ...in prose, not in code
                continue
            m = MD_HEAD.match(line)
            if m:
                heads.append((len(m.group(1)), m.group(2).strip(), n))
    elif suffix == ".py":
        for n, line in enumerate(lines):
            m = PY_DEF.match(line)
            if m and len(m.group(1)) <= 4:          # top level + one nesting
                level = 1 if not m.group(1) else 2
                heads.append((level, f"{m.group(2)} {m.group(3)}", n))
    return heads


def summarise(lines: list[str], start: int, end: int) -> str:
    """First substantive line in [start, end) — the node's one-line gist."""
    for line in lines[start:end]:
        s = line.strip().lstrip("#*->|").strip()
        if len(s) > 15 and not s.startswith(("```", "---", "<!--", "import ", "from ")):
            return s[:120]
    return ""


def find_refs(lines: list[str], start: int, end: int, limit: int = 8) -> list[str]:
    """Cross-references pointing out of this node — what similarity search misses."""
    blob, seen = "\n".join(lines[start:end]), []
    for pat in REF_PATS:
        for m in pat.finditer(blob):
            ref = (m.group(1) if m.groups() else m.group(0)).strip(".,;:)")
            low = ref.lower()
            if ref and low not in {r.lower() for r in seen} \
                   and not ref.startswith(("http", "#")):
                seen.append(ref)
                if len(seen) >= limit:
                    return seen
    return seen


# --------------------------------------------------------------------- build

def build(root: pathlib.Path, globs: list[str]) -> dict:
    """Walk the corpus and emit {id: node} with dotted ids (file → headings)."""
    nodes: dict[str, dict] = {}
    files = [p for p in sorted(root.rglob("*"))
             if p.is_file() and not any(part in IGNORE for part in p.parts)
             and p.suffix.lower() in TEXT_EXT]
    if globs:
        from fnmatch import fnmatch
        files = [p for p in files
                 if any(fnmatch(str(p.relative_to(root)), g) for g in globs)]

    for f_i, path in enumerate(files, 1):
        rel   = str(path.relative_to(root))
        try:
            lines = lines_of(path)
        except OSError:
            continue
        fid   = str(f_i)
        heads = outline(path, lines)
        nodes[fid] = {"id": fid, "title": rel, "path": rel, "level": 0,
                      "lines": [1, len(lines)], "children": [],
                      "summary": summarise(lines, 0, min(len(lines), 40)),
                      "refs": find_refs(lines, 0, len(lines))}
        # A heading's span runs to the next heading of equal-or-shallower level.
        stack: list[tuple[int, str]] = [(0, fid)]
        counters: dict[str, int] = {}
        for h_i, (level, title, start) in enumerate(heads):
            end = len(lines)
            for nxt_level, _, nxt_start in heads[h_i + 1:]:
                if nxt_level <= level:
                    end = nxt_start
                    break
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else fid
            counters[parent] = counters.get(parent, 0) + 1
            nid = f"{parent}.{counters[parent]}"
            nodes[nid] = {"id": nid, "title": title, "path": rel, "level": level,
                          "lines": [start + 1, end], "children": [],
                          "summary": summarise(lines, start + 1, end),
                          "refs": find_refs(lines, start, end)}
            nodes[parent]["children"].append(nid)
            stack.append((level, nid))
    return {"root": str(root), "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "files": len(files), "nodes": nodes}


# -------------------------------------------------------------- render/query

def render_toc(index: dict, depth: int, match: str | None, empty: str = "(empty index)") -> str:
    nodes = index["nodes"]
    keep  = None
    if match:
        rx   = re.compile(match, re.I)
        keep = set()
        for nid, n in nodes.items():
            if rx.search(n["title"]) or rx.search(n["summary"]):
                parts = nid.split(".")
                keep |= {".".join(parts[:i + 1]) for i in range(len(parts))}
    out = []

    def walk(nid: str, indent: int):
        n = nodes[nid]
        if keep is not None and nid not in keep:
            return
        span    = n["lines"]
        summary = f" — {n['summary']}" if n["summary"] else ""
        flag    = f"  ↪{len(n['refs'])}" if n["refs"] else ""
        out.append(f"{'  ' * indent}[{nid}] {n['title']} "
                   f"(L{span[0]}-{span[1]}){summary[:100]}{flag}")
        if indent < depth:
            for child in n["children"]:
                walk(child, indent + 1)

    for nid in sorted((k for k in nodes if "." not in k), key=int):
        walk(nid, 0)
    return "\n".join(out) or empty


def read_nodes(index: dict, root: pathlib.Path, ids: list[str], budget: int) -> str:
    nodes, chunks, used = index["nodes"], [], 0
    cap = budget * CHARS_PER_TOK
    for nid in ids:
        n = nodes.get(nid)
        if not n:
            chunks.append(f"### [{nid}] ERROR: no such node")
            continue
        lines = lines_of(root / n["path"])
        start, end = n["lines"]
        body = "\n".join(f"{i}\t{lines[i - 1]}"
                         for i in range(start, min(end, len(lines)) + 1))
        if used + len(body) > cap:
            body = body[:max(0, cap - used)] + "\n... [budget exhausted]"
        used += len(body)
        chunks.append(f"### [{nid}] {n['title']}  ({n['path']}:{start}-{end})\n{body}")
        if used >= cap:
            chunks.append(f"[stopped: {budget}-token budget reached]")
            break
    return "\n\n".join(chunks)


def main() -> int:
    ap  = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["build", "toc", "read", "refs", "search", "stats"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--glob", action="append", default=[])
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--budget", type=int, default=6000)
    a   = ap.parse_args()
    idx = pathlib.Path(a.index)

    if a.command == "build":
        root  = pathlib.Path(a.args[0] if a.args else ".").resolve()
        index = build(root, a.glob)
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text(json.dumps(index, indent=1))
        toc_tokens = len(render_toc(index, 9, None)) // CHARS_PER_TOK
        print(f"Indexed {index['files']} files → {len(index['nodes'])} nodes "
              f"in {idx} (full ToC ≈ {toc_tokens} tokens)")
        return 0

    if not idx.is_file():
        print(f"ERROR: no index at {idx} — run: python3 -m panda.pageindex build .",
              file=sys.stderr)
        return 1
    index = json.loads(idx.read_text())
    root  = pathlib.Path(index["root"])

    if a.command == "toc":
        print(render_toc(index, a.depth, None))
    elif a.command == "search":
        if not a.args:
            print("ERROR: search needs a term", file=sys.stderr)
            return 1
        print(render_toc(index, 9, a.args[0],
                         empty="(no title or summary matched — reason about where "
                               "the answer would live and pick from `toc` instead)"))
    elif a.command == "read":
        if not a.args:
            print("ERROR: read needs node ids", file=sys.stderr)
            return 1
        print(read_nodes(index, root, a.args, a.budget))
    elif a.command == "refs":
        for nid in a.args:
            n = index["nodes"].get(nid)
            print(f"[{nid}] {n['title']}: {', '.join(n['refs']) or '(none)'}"
                  if n else f"[{nid}] ERROR: no such node")
    elif a.command == "stats":
        nodes = index["nodes"]
        print(f"root={index['root']} files={index['files']} nodes={len(nodes)} "
              f"built={index['generated']}\n"
              f"ToC tokens: depth1≈{len(render_toc(index, 1, None)) // CHARS_PER_TOK} "
              f"depth2≈{len(render_toc(index, 2, None)) // CHARS_PER_TOK} "
              f"full≈{len(render_toc(index, 9, None)) // CHARS_PER_TOK}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:      # piping into head/less is normal usage
        sys.exit(0)
