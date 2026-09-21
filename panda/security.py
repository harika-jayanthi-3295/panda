"""
Day 2 – Security
Teaches : policy-based access control via a deny-list and escalating modes.
Design  : READ_TOOLS and DENY_PATTERNS are module constants; Policy.check
          returns None (allow) or a reason string (block).
"""
import re

# Tools that only read state — always safe in any mode.
READ_TOOLS = {"read_file", "list_files", "grep"}

# Bash patterns blocked regardless of mode (destructive rm, privilege
# escalation, raw disk ops, remote exec, forced git rewrite, device writes).
DENY_PATTERNS = [
    r"rm\s+\S*[rf]{2}\S*\s+(\$HOME|~|/)",   # rm -rf/-fr targeting / or ~
    r"\bsudo\b",                              # any privilege escalation
    r"\b(mkfs|dd\s+if=)\b",                  # disk format / raw copy
    r"curl\b[^|]*\|\s*(ba)?sh\b",            # curl | sh remote exec
    r"git\s+push\s+--force\b",               # destructive git rewrite
    r">\s*/dev/sd[a-z]",                     # raw block device write
]


class Policy:
    """Gate-keeps tool calls with three escalating permission modes.

    read-only : only READ_TOOLS are permitted; everything else is blocked.
    safe      : non-read calls are forwarded to an approver callback;
                the default approver always refuses (safe without a human
                is equivalent to read-only for mutating tools).
    yolo      : all calls pass except bash commands matching DENY_PATTERNS.
    """

    def __init__(self, mode: str = "safe", approver=None):
        """approver(call, reason) -> bool; defaults to refusing everything."""
        if mode not in ("read-only", "safe", "yolo"):
            raise ValueError(f"unknown mode {mode!r}")
        self.mode     = mode
        self.approver = approver or (lambda _c, _r: False)

    def check(self, call: dict) -> str | None:
        """Return None to allow the call, or a reason string to block it.

        Evaluation order (earlier rules short-circuit later ones):
          1. bash deny-patterns  — absolute block, no mode can override.
          2. READ_TOOLS / yolo   — always allow.
          3. read-only mode      — block all remaining calls.
          4. safe mode           — ask approver; block unless it returns True.
        """
        if call["name"] == "bash":
            cmd = call["args"].get("command", "")
            for pat in DENY_PATTERNS:
                if re.search(pat, cmd, re.IGNORECASE):
                    return f"command matches deny pattern ({pat!r})"

        if call["name"] in READ_TOOLS or self.mode == "yolo":
            return None

        if self.mode == "read-only":
            return f"{call['name']!r} is not permitted in read-only mode"

        # safe mode: delegate to the human approver.
        if self.approver(call, f"allow {call['name']!r}?"):
            return None
        return f"{call['name']!r} was not approved"
