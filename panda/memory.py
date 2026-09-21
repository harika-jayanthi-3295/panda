"""
Day 3 – Memory
Teaches : durable project memory injected into the system prompt each session.
Design  : panda.md accumulates bullet facts across runs; build_system_prompt
          layers base instructions, platform info, memory, and caller extras
          so every module above it stays unaware of session state.
"""
import pathlib, platform

MEMORY_FILE = "panda.md"

# Base instructions baked into every panda session.
_BASE = (
    "You are panda, a small sharp coding agent working inside one directory "
    "with the tools provided. "
    "Act, don't narrate. "
    "Inspect before assuming. "
    "Prefer edit_file for small changes. "
    "Verify after building by running or re-reading. "
    "Never repeat a failing call unchanged. "
    "When complete, reply with a short summary and stop calling tools."
)


def build_system_prompt(workdir: str, extra: str = "") -> str:
    """Compose the layered system prompt for a panda session.

    Layers joined by blank lines:
      1. Base panda instructions.
      2. Platform name and real working directory.
      3. Project memory from panda.md, when the file exists.
      4. extra, when non-empty.
    """
    parts = [
        _BASE,
        f"Platform: {platform.system()}. Working directory: {workdir}.",
    ]
    mem = pathlib.Path(workdir) / MEMORY_FILE
    if mem.exists():
        parts.append(f"Project memory (panda.md):\n{mem.read_text().strip()}")
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def remember(workdir: str, note: str) -> str:
    """Append '- <note>' to panda.md and return a confirmation string."""
    (pathlib.Path(workdir) / MEMORY_FILE).open("a").write(f"- {note}\n")
    return "Remembered in panda.md"
