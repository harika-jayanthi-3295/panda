"""
Day 3 – Skills
Teaches : a filesystem-backed skill catalog that hints at capabilities in the
          system prompt and loads full skill text on demand.
Design  : each skill is a directory under skills/ containing SKILL.md; the
          description is pulled from a "description:" front-matter line when
          present, falling back to the directory name.
"""
import pathlib

SKILLS_DIR = "skills"


def catalog(workdir: str) -> dict:
    """Return {name: {"description", "path"}} for every skill found in workdir/skills/."""
    root = pathlib.Path(workdir) / SKILLS_DIR
    if not root.is_dir():
        return {}
    result = {}
    for skill_dir in sorted(root.iterdir()):
        md = skill_dir / "SKILL.md"
        if not md.is_file():
            continue
        desc = skill_dir.name          # default when no front-matter line
        for line in md.read_text().splitlines():
            if line.lower().strip().startswith("description:"):
                desc = line.split(":", 1)[1].strip()
                break
        result[skill_dir.name] = {"description": desc, "path": str(md)}
    return result


def catalog_prompt(workdir: str) -> str:
    """Return a one-liner skills hint for injection into the system prompt.

    Returns an empty string when no skills exist so the caller can
    omit the section entirely without special-casing.
    """
    skills = catalog(workdir)
    if not skills:
        return ""
    lines = ["Skills available (load one with the use_skill tool when relevant):"]
    for name, info in skills.items():
        lines.append(f"- {name}: {info['description']}")
    return "\n".join(lines)


def read_skill(workdir: str, name: str) -> str:
    """Return the full SKILL.md text for skill *name*, or an error on miss."""
    skills = catalog(workdir)
    if name not in skills:
        avail = ", ".join(skills) or "(none)"
        return f"ERROR: no skill named {name!r}. Available: {avail}"
    return pathlib.Path(skills[name]["path"]).read_text()
