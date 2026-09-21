"""
Day 2 – Tools
Teaches : the tool protocol (spec + run) and the path-safety sandbox pattern.
Design  : Tool is a plain dataclass; tool() builds spec from the function
          signature so documentation lives once; core_tools closes over a
          resolved workdir path and every path flows through one resolve()
          that enforces the sandbox boundary with a single is_relative_to check.
"""
import fnmatch, inspect, pathlib, re, subprocess
from dataclasses import dataclass
from typing import Callable

_IGNORE = {".git", "node_modules", "__pycache__", ".venv"}


@dataclass
class Tool:
    """Minimal tool protocol consumed by run_loop: name, provider spec, callable."""
    name: str
    spec: dict       # {"schema": {"name", "description", "parameters"}}
    run:  Callable


def tool(description: str, **param_docs):
    """Decorator that turns a plain function into a Tool.

    Reads argument names and defaults from the function signature.
    Parameters without defaults are marked required.
    All parameters are string-typed on purpose — the model always sends strings.
    Keyword arguments to tool() supply per-parameter description text.
    """
    def wrap(fn):
        props, required = {}, []
        for pname, p in inspect.signature(fn).parameters.items():
            props[pname] = {"type": "string",
                            "description": param_docs.get(pname, pname)}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        return Tool(
            name=fn.__name__,
            spec={"schema": {
                "name": fn.__name__, "description": description,
                "parameters": {"type": "object", "properties": props,
                               "required": required},
            }},
            run=fn,
        )
    return wrap


def core_tools(workdir: str) -> list[Tool]:
    """Return the six standard sandboxed tools closed over workdir.

    Every tool that touches the file system routes its path argument through
    resolve(), which rejects any path whose realpath escapes the sandbox.
    """
    wd = pathlib.Path(workdir).resolve()

    def resolve(path: str) -> pathlib.Path:
        """Return absolute path inside wd; raise PermissionError if it escapes."""
        p = (wd / path).resolve()
        if not p.is_relative_to(wd):
            raise PermissionError(f"{path!r} escapes the working directory")
        return p

    @tool("Read a file with 1-based line numbers",
          path="path relative to workdir")
    def read_file(path: str) -> str:
        lines = resolve(path).read_text(errors="replace").splitlines()
        total = len(lines)
        body  = "\n".join(f"{i+1}\t{l}" for i, l in enumerate(lines[:4000]))
        # Hard cap: note the total so the model knows data was cut.
        if total > 4000:
            body += f"\n... [{total} lines total, truncated at 4000]"
        return body

    @tool("Write content to a file, creating parent directories as needed",
          path="path relative to workdir", content="full file content")
    def write_file(path: str, content: str) -> str:
        p = resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Wrote {len(content)} chars to {path}"

    @tool("Replace an exact text snippet in a file (must appear exactly once)",
          path="path relative to workdir", old="exact text to replace",
          new="replacement text")
    def edit_file(path: str, old: str, new: str) -> str:
        text  = resolve(path).read_text()
        count = text.count(old)
        # Zero matches: the model miscopied the snippet — tell it to re-read.
        if count == 0:
            return "ERROR: snippet not found — read the file and copy it exactly"
        # Multiple matches: context window too narrow to be unique.
        if count > 1:
            return (f"ERROR: snippet appears {count} times — "
                    "include more context to make it unique")
        resolve(path).write_text(text.replace(old, new, 1))
        return f"Edited {path}"

    @tool("Run a shell command in the workdir",
          command="shell command", timeout="max seconds (default 120)")
    def bash(command: str, timeout: str = "120") -> str:
        t = int(timeout)
        try:
            proc = subprocess.run(
                command, shell=True, cwd=wd,
                capture_output=True, text=True, timeout=t,
            )
            out = proc.stdout + proc.stderr
            if not out:
                return f"(exit {proc.returncode}, no output)"
            # Keep first and last 6 KB to preserve context around errors.
            if len(out) > 12000:
                mid = f"\n...[{len(out) - 12000} chars truncated]...\n"
                out = out[:6000] + mid + out[-6000:]
            return out
        except subprocess.TimeoutExpired:
            return f"ERROR: timed out after {t}s"

    @tool("List files matching a glob pattern (skips .git, node_modules, etc.)",
          pattern="glob pattern, default **/*")
    def list_files(pattern: str = "**/*") -> str:
        matches = []
        for p in sorted(wd.rglob("*")):
            if any(part in _IGNORE for part in p.parts):
                continue
            rel = str(p.relative_to(wd))
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(p.name, pattern):
                matches.append(rel)
        if len(matches) > 500:
            extra = len(matches) - 500
            matches = matches[:500] + [f"... and {extra} more"]
        return "\n".join(matches) or "(empty)"

    @tool("Search file contents with a regex",
          regex="Python regex", pattern="filename glob, default *")
    def grep(regex: str, pattern: str = "*") -> str:
        try:
            rx = re.compile(regex)
        except re.error as exc:
            return f"ERROR: invalid regex — {exc}"
        hits: list[str] = []
        for p in sorted(wd.rglob("*")):
            if not p.is_file() or any(part in _IGNORE for part in p.parts):
                continue
            rel = str(p.relative_to(wd))
            if not (fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(p.name, pattern)):
                continue
            try:
                for lineno, line in enumerate(
                    p.read_text(errors="replace").splitlines(), 1
                ):
                    if rx.search(line):
                        hits.append(f"{rel}:{lineno}: {line[:200]}")
                        if len(hits) >= 200:
                            return "\n".join(hits)
            except OSError:
                continue
        return "\n".join(hits) or "(no matches)"

    return [read_file, write_file, edit_file, bash, list_files, grep]
