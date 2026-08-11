#!/usr/bin/env python3
"""
Fleet build — three products proved through panda.run_fleet.

Phase 1 : parallel builds (artisan-coffee, taskman, viper)
Phase 2 : design-director review + fix in the SAME session (resume each)
Phase 3 : mechanical verification + results table
"""
import pathlib, re, subprocess, sys, threading, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from panda import Harness, run_fleet

# ── Project root ───────────────────────────────────────────────────────────────
ROOT = pathlib.Path("/tmp/panda_fleet")
ROOT.mkdir(exist_ok=True)

PROJECTS = ["artisan-coffee", "taskman", "viper"]

# ── Skill file (verbatim quality bar) ─────────────────────────────────────────
SKILL_MD = """\
# Design Engineering

Quality bar — every item is mandatory:
- A real design system as CSS custom properties
- At least 9 distinct sections for a landing page
- At least 1,200 words of real copy, no lorem ipsum
- At least 4 hand-drawn inline SVG illustrations, one being a product artifact in the hero
- At least 3 working interactive behaviors
- Responsive at 360, 768, and 1280
- Semantic HTML with focus states
- A self-review pass before finishing that counts sections, words, SVGs, and
  interactions against these minimums and fixes any shortfall
"""

# ── Seed each workdir with the skill ──────────────────────────────────────────
for name in PROJECTS:
    skill_path = ROOT / name / "skills" / "design-engineering"
    skill_path.mkdir(parents=True, exist_ok=True)
    (skill_path / "SKILL.md").write_text(SKILL_MD)
print("SKILL.md written to all three workdirs.\n")

# ── Build tasks (Phase 1) ──────────────────────────────────────────────────────
P1_TASKS = {

"artisan-coffee": """\
Use your use_skill tool to load the design-engineering skill first.

Build a SINGLE self-contained index.html for 'Kaapi Kalakar' — a specialty \
single-origin coffee roaster in Goa, India. All CSS and JS must be inline.

MANDATORY structure (9 named sections — use <section id="..."> for each):
1. sticky-nav  — brand logo (inline SVG coffee cup icon), links to all sections, dark-mode toggle button
2. hero        — headline, sub-headline, CTA button, and one HAND-DRAWN inline SVG of a kraft-paper coffee bag (the product artifact) showing the Kaapi Kalakar label
3. story       — 200+ word narrative about the founders, Goa's Western Ghats, and the estate-to-cup philosophy
4. origins     — 6 cards, each: estate name, region (Coorg/Chikmagalur/Araku/Wayanad/etc.), process (washed/natural/honey), tasting notes, price per 250g (₹450–₹850)
5. subscribe   — 3-tier table: Starter (250g/mo, ₹599), Explorer (500g/mo, ₹999, best-value badge), Connoisseur (1kg/mo, ₹1799); a JS toggle that switches between monthly and annual prices (annual = 10 months' price)
6. brew-guide  — JS tab switcher with 4 tabs: Pour Over, French Press, AeroPress, Cold Brew; each tab shows ratio, grind size, steps, and a small hand-drawn inline SVG of the equipment
7. faq         — accordion with 6 Q&A pairs; clicking a question toggles the answer; aria-expanded attribute updated
8. testimonials — 3 customer quotes with name, city, and star rating
9. footer      — address, phone, email, social icon links (inline SVG), copyright

DESIGN SYSTEM (CSS custom properties at :root, used everywhere):
--color-brand, --color-bg, --color-surface, --color-text, --color-accent,
--font-heading, --font-body, --space-xs through --space-2xl, --radius-sm/md/lg,
--shadow-card, --transition-base

INTERACTIVITY (all in vanilla JS, no libraries):
1. Dark-mode toggle — adds/removes .dark class on <html>; persists to localStorage('theme')
2. Subscribe monthly/annual toggle — updates all price elements
3. Brew-guide tabs — show/hide tab panels
4. FAQ accordion — toggle answer visibility + aria-expanded

SVG ILLUSTRATIONS (hand-drawn style, inline, no external files):
1. Hero: kraft-paper coffee bag product shot with label, beans spilling out
2. India coffee origin map in the origins section header
3. Brewing equipment illustration in the brew-guide header
4. Coffee cherry / plant illustration in the story section

COPY: write ≥1,200 words of real, specific copy about Goa coffee, the estates, \
the roasting process, tasting notes, and brew culture. NO lorem ipsum.

RESPONSIVE: media queries for 360px, 768px, and 1280px. Mobile: stack columns. \
Tablet: 2-col grid. Desktop: full layout.

SEMANTIC HTML: use <header>, <nav>, <main>, <section>, <article>, <footer>. \
Every interactive element has a visible :focus-visible outline.

SELF-REVIEW before writing the final file:
- Count sections (need ≥9). List them.
- Count words in copy text (need ≥1200). State the count.
- Count inline SVGs (need ≥4). List them.
- Count interactive behaviors (need ≥3). List them.
- Fix any shortfall, then write the complete file.
""",

"taskman": """\
Build a Python CLI task manager in two files: taskman.py and test_taskman.py.

━━ taskman.py ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
argparse with these subcommands:

  add TITLE [--due DATE] [--tag TAG]
    Auto-increment ID (1-based), status="open", store created_at as ISO date.
    Print: "Added task #N: TITLE"

  list [--tag TAG] [--status {open,done,all}]
    Aligned table with columns: ID  Status  Title  Due  Tag
    Column widths calculated from data. Sort by ID ascending.
    Default shows all tasks. Filter by --tag or --status.
    Show "(no tasks)" when empty.

  done ID
    Mark task done. Print: "Marked #N done."
    Error if ID not found.

  rm ID
    Delete task. Print: "Removed #N."
    Error if ID not found.

  stats
    Table: Total / Open / Done counts.
    Second table: tag breakdown (tag, count, open, done) sorted by count desc.
    Show even when zero tasks.

Persistence: read/write tasks.json in cwd. Create if missing.
Errors: write to stderr, exit 1.

━━ test_taskman.py ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
12 test cases using unittest.TestCase + subprocess.run to call:
  python3 <path_to_taskman.py> <args>
with cwd=self.tmpdir (a tempfile.mkdtemp() created in setUp).

Tests:
1. test_add_basic          — add returns "Added task #1"
2. test_add_with_due_tag   — add --due 2026-12-01 --tag work; list shows due+tag
3. test_list_empty         — list on fresh store shows "(no tasks)"
4. test_list_all           — add 3 tasks; list shows all 3 rows
5. test_list_filter_tag    — add tasks with different tags; --tag filters correctly
6. test_list_filter_status — mix open/done; --status done shows only done
7. test_done_valid         — done marks task; list shows "done"
8. test_done_invalid       — done 999 exits 1 and prints error
9. test_rm_valid           — rm removes task; list no longer shows it
10. test_rm_invalid        — rm 999 exits 1
11. test_stats_empty       — stats on fresh store shows zeros
12. test_stats_populated   — add 3 tasks, done 1; stats shows 3 total / 2 open / 1 done

After writing both files, run: python3 -m unittest test_taskman -v
from the project directory. ALL 12 tests must be green. Fix any failures.
""",

"viper": """\
Build a canvas snake game in a single self-contained index.html.

━━ Game mechanics ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 20×20 grid drawn on a <canvas> element
- Movement driven by requestAnimationFrame with a timestamp-based step interval
  (initial interval: 150ms; decreases by 10ms every 5 foods eaten, min 60ms)
- Snake starts as 3 segments in the center moving right
- Food spawns at a random empty cell; eating it grows the snake by 1 and scores +10
- Collision: wall OR self → game over
- Score and high score (localStorage key "viper-hi") shown in a HUD above the canvas

━━ Controls ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Arrow keys / WASD: change direction (ignore 180° reversal)
- P: pause / resume
- Space: restart on game-over screen; also pause/resume during play
- Controls shown as a legend below the canvas

━━ Screens ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Start screen: game title "VIPER", tagline, "Press Space or Enter to start"
- Play screen: animated snake and food
- Game-over screen: "GAME OVER", final score, high score, "Press Space to restart"
- Pause overlay: "PAUSED — Press P or Space to continue"

━━ Visuals ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Dark background (#0f0f1a), neon-green snake (#39ff14), bright-red food (#ff4444)
- Snake head slightly different shade from body
- Smooth grid lines in a subtle dark color
- HUD: monospace font, score left-aligned, high score right-aligned

━━ Responsive ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Canvas size = min(viewportWidth, viewportHeight) * 0.85 (recalculated on resize)
- Cell size = canvas size / 20
- Works at 360px and 1280px

━━ Self-check before writing ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Verify: requestAnimationFrame loop present, localStorage for high score,
speed-up every 5 foods, pause/restart, start screen, game-over screen.
All in one HTML file. No external resources.
"""
}

# ── Thread-safe print ──────────────────────────────────────────────────────────
_lock = threading.Lock()
def tprint(msg):
    with _lock:
        print(msg, flush=True)

# ── Quiet on_event (progress dots only) ───────────────────────────────────────
def make_quiet_event(name):
    count = [0]
    def on_event(kind, payload):
        count[0] += 1
        if count[0] % 5 == 0:
            tprint(f"  [{name}] … {count[0]} events")
    return on_event

# ── Harness factories ──────────────────────────────────────────────────────────
def make_p1(workdir: str) -> Harness:
    name = pathlib.Path(workdir).name
    return Harness(workdir=workdir, max_turns=100, on_event=make_quiet_event(name))

def make_p2(workdir: str) -> Harness:
    name = pathlib.Path(workdir).name
    h = Harness(workdir=workdir, max_turns=60, on_event=make_quiet_event(name))
    loaded = h.resume()
    if loaded:
        tprint(f"  [{name}] resumed {len(h.messages)} messages")
    return h

# ══ Phase 1: Build ════════════════════════════════════════════════════════════
print("=" * 60)
print("PHASE 1 — BUILDING ALL THREE PROJECTS IN PARALLEL")
print("=" * 60)
t0 = time.time()

p1_jobs = [
    {"name": n, "workdir": str(ROOT / n), "task": P1_TASKS[n]}
    for n in PROJECTS
]
p1_results = run_fleet(p1_jobs, make_p1, max_workers=3)

elapsed = time.time() - t0
print(f"\nPhase 1 complete in {elapsed/60:.1f} min")
for r in p1_results:
    ok = "✓" if r["ok"] else "✗"
    print(f"  {ok} {r['name']}: {r['report'][:160].strip()}")

# ══ Phase 2: Review & Fix ═════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PHASE 2 — DESIGN-DIRECTOR REVIEW (SAME SESSION, RESUME)")
print("=" * 60)
t1 = time.time()

REVIEW = (
    "Review every file you produced against the skill bar as a demanding "
    "design director; list 12 concrete deficiencies; fix them all; verify again."
)
p2_jobs = [
    {"name": n, "workdir": str(ROOT / n), "task": REVIEW}
    for n in PROJECTS
]
p2_results = run_fleet(p2_jobs, make_p2, max_workers=3)

elapsed2 = time.time() - t1
print(f"\nPhase 2 complete in {elapsed2/60:.1f} min")
for r in p2_results:
    ok = "✓" if r["ok"] else "✗"
    print(f"  {ok} {r['name']}: {r['report'][:160].strip()}")

# ══ Phase 3: Mechanical verification ══════════════════════════════════════════
print("\n" + "=" * 60)
print("PHASE 3 — MECHANICAL VERIFICATION")
print("=" * 60)

results_table = []

# ── artisan-coffee ────────────────────────────────────────────────────────────
ac_dir  = ROOT / "artisan-coffee"
ac_html = ac_dir / "index.html"
ac_ok   = True
ac_notes = []

if not ac_html.exists():
    ac_ok = False; ac_notes.append("index.html missing")
else:
    src = ac_html.read_text(errors="ignore")
    word_count = len(re.findall(r'\b\w+\b',
        re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style)[^>]*>.*?</\1>', '', src, flags=re.S))))
    if "localStorage" not in src:
        ac_ok = False; ac_notes.append("localStorage missing")
    if not re.search(r'accordion|aria-expanded|\.toggle\b', src, re.I):
        ac_ok = False; ac_notes.append("accordion/aria-expanded missing")
    svgs = len(re.findall(r'<svg\b', src, re.I))
    if svgs < 4:
        ac_ok = False; ac_notes.append(f"only {svgs}/4 SVGs")
    if word_count < 1200:
        ac_ok = False; ac_notes.append(f"only ~{word_count} words (need ≥1200)")
    else:
        ac_notes.append(f"~{word_count} words")
    ac_notes.append(f"{svgs} inline SVGs")

print(f"artisan-coffee: {'PASS' if ac_ok else 'FAIL'}  {'; '.join(ac_notes)}")
results_table.append(("artisan-coffee", ac_ok, ac_notes))

# ── taskman ───────────────────────────────────────────────────────────────────
tm_dir  = ROOT / "taskman"
tm_py   = tm_dir / "taskman.py"
tm_test = tm_dir / "test_taskman.py"
tm_ok   = True
tm_notes = []

if not tm_py.exists():
    tm_ok = False; tm_notes.append("taskman.py missing")
if not tm_test.exists():
    tm_ok = False; tm_notes.append("test_taskman.py missing")

if tm_ok:
    res = subprocess.run(
        [sys.executable, "-m", "unittest", "test_taskman", "-v"],
        cwd=str(tm_dir), capture_output=True, text=True, timeout=60
    )
    if res.returncode == 0:
        passed = len(re.findall(r'\.\.\.|ok\b', res.stderr))
        tm_notes.append(f"all tests green (rc=0)")
    else:
        tm_ok = False
        tm_notes.append(f"tests FAILED (rc={res.returncode})")
        tm_notes.append(res.stderr[-400:].strip())

print(f"taskman:        {'PASS' if tm_ok else 'FAIL'}  {'; '.join(tm_notes[:2])}")
results_table.append(("taskman", tm_ok, tm_notes))

# ── viper ─────────────────────────────────────────────────────────────────────
vp_dir  = ROOT / "viper"
vp_html = vp_dir / "index.html"
vp_ok   = True
vp_notes = []

if not vp_html.exists():
    vp_ok = False; vp_notes.append("index.html missing")
else:
    src = vp_html.read_text(errors="ignore")
    if "requestAnimationFrame" not in src:
        vp_ok = False; vp_notes.append("requestAnimationFrame missing")
    if "localStorage" not in src:
        vp_ok = False; vp_notes.append("localStorage missing")
    if not re.search(r'pause|Pause|PAUSE', src):
        vp_ok = False; vp_notes.append("pause missing")
    if not re.search(r'restart|Restart|RESTART|game.?over', src, re.I):
        vp_ok = False; vp_notes.append("restart/game-over missing")
    if not vp_notes:
        vp_notes.append("requestAnimationFrame ✓  localStorage ✓  pause ✓  restart ✓")

print(f"viper:          {'PASS' if vp_ok else 'FAIL'}  {'; '.join(vp_notes)}")
results_table.append(("viper", vp_ok, vp_notes))

# ══ Results table ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("RESULTS TABLE")
print("=" * 60)
print(f"{'Project':<18} {'Result':<8} {'Notes'}")
print("-" * 60)
for name, ok, notes in results_table:
    result = "PASS ✓" if ok else "FAIL ✗"
    print(f"{name:<18} {result:<8} {notes[0] if notes else ''}")

total = time.time() - t0
print(f"\nTotal time: {total/60:.1f} min")
all_ok = all(ok for _, ok, _ in results_table)
print("Overall:", "ALL PASS ✓" if all_ok else "SOME FAILURES — run review pass")
sys.exit(0 if all_ok else 1)
