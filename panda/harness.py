"""
Day 4 – Harness
Teaches : composing a week of modules into one coherent, resumable coding agent.
Design  : Harness is the only public class; it wires workdir, model, policy,
          tools, system prompt, session persistence, compaction, and optional
          sub-agents into run_loop. No logic lives here that belongs elsewhere.
"""
import os, pathlib
from . import session
from . import loop
from . import provider
from .context  import compact
from .memory   import build_system_prompt, remember as _remember
from .security import Policy
from .skills   import catalog_prompt, read_skill
from .subagent import subagent_tool
from .tools    import Tool, core_tools, tool


class Harness:
    """One configured panda agent over a working directory.

    Construct once; call run(task) one or more times.
    Call resume() before run() to continue an interrupted session.
    """

    def __init__(
        self,
        workdir: str = ".",
        model: str | None = None,
        policy: Policy | None = None,
        extra_tools: list[Tool] | None = None,
        system_extra: str = "",
        on_event=None,
        budget_tokens: int = 600_000,
        max_turns: int = 120,
        session_path: str | None = None,
        enable_subagents: bool = True,
        persist: bool = True,
        _depth: int = 0,
    ):
        self.workdir       = str(pathlib.Path(workdir).resolve())
        pathlib.Path(self.workdir).mkdir(parents=True, exist_ok=True)
        self.model         = (model or os.environ.get("PANDA_MODEL")
                              or provider.DEFAULT_MODEL)
        self.policy        = policy or Policy("yolo")
        self.budget_tokens = budget_tokens
        self.max_turns     = max_turns
        self.session_path  = session_path
        self.on_event      = on_event or _default_event
        self.persist       = persist
        self.messages: list[dict] = []
        self._stopped      = False

        # ── Tools ──────────────────────────────────────────────────────────
        self.tools = {t.name: t for t in core_tools(self.workdir)}

        @tool("Persist a fact to panda.md so future sessions remember it",
              note="the fact to store")
        def remember(note: str) -> str:
            return _remember(self.workdir, note)
        self.tools["remember"] = remember

        cat = catalog_prompt(self.workdir)
        if cat:
            @tool("Load the full text of a named skill into this context",
                  name="skill name")
            def use_skill(name: str) -> str:
                return read_skill(self.workdir, name)
            self.tools["use_skill"] = use_skill

        if enable_subagents:
            def _make_child(d: int) -> "Harness":
                # Children are ephemeral: persist=False so their sessions
                # never appear in latest() and cannot hijack --resume.
                return Harness(workdir=self.workdir, model=self.model,
                               policy=self.policy, persist=False, _depth=d)
            self.tools["spawn_agent"] = subagent_tool(_make_child, _depth)

        for t_extra in (extra_tools or []):
            self.tools[t_extra.name] = t_extra

        # ── System prompt ──────────────────────────────────────────────────
        extra = "\n\n".join(filter(None, [cat, system_extra]))
        self.system = build_system_prompt(self.workdir, extra)

    def stop(self) -> None:
        """Stop the running session."""
        self._stopped = True

    def resume(self, path: str | None = None) -> bool:
        """Load the latest (or given) session; return True when messages loaded."""
        p = path or session.latest(self.workdir)
        if not p:
            return False
        self.messages = session.load(p)
        self.session_path = p
        return bool(self.messages)

    def run(self, task: str) -> str:
        """Append task, run the loop, persist every message, return final text."""
        if self.persist and not self.session_path:
            self.session_path = session.new_session(self.workdir, task[:32])

        user_msg = {"role": "user", "text": task}
        self.messages.append(user_msg)
        if self.persist and self.session_path:
            session.append(self.session_path, user_msg)
        recorded = len(self.messages)

        def _flush():
            nonlocal recorded
            if self.persist and self.session_path:
                # Clamp: before_turn compaction may have shrunk the list.
                recorded = min(recorded, len(self.messages))
                while recorded < len(self.messages):
                    session.append(self.session_path, self.messages[recorded])
                    recorded += 1

        def _on_event(kind, payload):
            _flush()
            self.on_event(kind, payload)

        def _before_turn(msgs: list[dict]) -> list[dict]:
            _flush()
            return compact(self.model, msgs, self.budget_tokens)

        result = loop.run_loop(
            model=self.model, system=self.system, messages=self.messages,
            tools=self.tools, on_event=_on_event,
            before_tool=self.policy.check, before_turn=_before_turn,
            max_turns=self.max_turns, should_stop=lambda: self._stopped,
        )
        _flush()
        return result


def _default_event(kind: str, payload) -> None:
    """Minimal event printer used when the caller supplies no on_event."""
    if kind == "assistant" and payload.get("text"):
        print(f"[assistant] {payload['text'][:240]}")
    elif kind == "tool_end":
        print(f"[{payload['call']['name']}] {str(payload['result'])[:120]}")
