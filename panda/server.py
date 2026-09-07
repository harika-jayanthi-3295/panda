"""
Panda Web UI – a Lovable-style browser interface for the panda harness.
Type a prompt, watch the agent think and act in real-time, inspect every
file it creates. Requires flask (pip install flask).

Usage:
    python3 -m panda.server              # http://localhost:7860
    python3 -m panda.server --port 8080
"""
from __future__ import annotations
import argparse, json, os, pathlib, queue, sys, tempfile, threading, time, uuid
from flask import Flask, Response, jsonify, request, send_file

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from panda import Harness

app = Flask(__name__)
_runs: dict[str, dict] = {}   # run_id -> {q, thread, workdir, harness}

# ─────────────────────────────────────────────────────────────────────────────
# SSE helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return _HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.post("/api/run")
def api_run():
    body     = request.get_json(force=True)
    task     = body.get("task", "").strip()
    workdir  = body.get("workdir", "").strip() or tempfile.mkdtemp(prefix="panda_")
    model    = body.get("model") or None
    mode     = body.get("mode", "yolo")

    if not task:
        return jsonify({"error": "task is required"}), 400

    run_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()

    from panda.security import Policy
    policy = Policy(mode)

    def on_event(kind: str, payload):
        if kind == "assistant":
            text = payload.get("text", "")
            calls = payload.get("tool_calls", [])
            if text:
                q.put(_sse("thinking", {"text": text}))
            for c in calls:
                args_preview = {k: str(v)[:200] for k, v in c.get("args", {}).items()}
                q.put(_sse("tool_call", {"name": c["name"], "args": args_preview}))
        elif kind == "tool_end":
            call   = payload.get("call", {})
            result = str(payload.get("result", ""))
            q.put(_sse("tool_result", {
                "name":    call.get("name", "?"),
                "result":  result[:600],
                "ok":      not result.startswith("ERROR"),
            }))

    def run_thread():
        try:
            h = Harness(workdir=workdir, model=model, policy=policy,
                        on_event=on_event, max_turns=120)
            _runs[run_id]["harness"] = h
            result = h.run(task)
            # build file list
            files = _list_files(workdir)
            q.put(_sse("complete", {"text": result, "workdir": workdir, "files": files}))
        except Exception as exc:
            q.put(_sse("error", {"message": str(exc)}))
        finally:
            q.put(None)  # sentinel

    t = threading.Thread(target=run_thread, daemon=True)
    _runs[run_id] = {"q": q, "thread": t, "workdir": workdir, "harness": None}
    t.start()
    return jsonify({"run_id": run_id, "workdir": workdir})


@app.get("/api/stream/<run_id>")
def api_stream(run_id: str):
    run = _runs.get(run_id)
    if not run:
        return "run not found", 404

    def generate():
        yield _sse("connected", {"run_id": run_id})
        while True:
            try:
                item = run["q"].get(timeout=30)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if item is None:
                break
            yield item

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no",
                             "Access-Control-Allow-Origin": "*"})


@app.post("/api/stop/<run_id>")
def api_stop(run_id: str):
    run = _runs.get(run_id)
    if not run:
        return jsonify({"error": "run not found"}), 404
    
    harness = run.get("harness")
    if harness:
        harness.stop()
    
    return jsonify({"status": "stopped"})


@app.get("/api/files")
def api_files():
    workdir = request.args.get("workdir", "")
    if not workdir:
        return jsonify([])
    return jsonify(_list_files(workdir))


@app.get("/api/file")
def api_file():
    path = request.args.get("path", "")
    if not path or not pathlib.Path(path).is_file():
        return "not found", 404
    return send_file(path, mimetype="text/plain")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _list_files(workdir: str) -> list[dict]:
    root = pathlib.Path(workdir)
    out  = []
    skip = {".panda", "__pycache__", ".git", "node_modules", "skills"}
    for p in sorted(root.rglob("*")):
        if any(s in p.parts for s in skip):
            continue
        if p.is_file():
            out.append({"name": p.name, "path": str(p),
                        "rel":  str(p.relative_to(root)),
                        "size": p.stat().st_size})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Embedded UI
# ─────────────────────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>panda — agent workspace</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:        #0d0d14;
    --surface:   #16161f;
    --border:    #2a2a3a;
    --text:      #e2e2f0;
    --muted:     #7070a0;
    --accent:    #7c6af7;
    --green:     #3dcc91;
    --orange:    #f5a623;
    --red:       #e05c5c;
    --blue:      #5ca8f5;
    --font-mono: "JetBrains Mono", "Fira Code", monospace;
    --radius:    8px;
  }
  html, body { height: 100%; background: var(--bg); color: var(--text);
               font-family: system-ui, sans-serif; font-size: 14px; }
  body { display: flex; flex-direction: column; }

  /* ── Top bar ── */
  header { display: flex; align-items: center; gap: 12px;
           padding: 10px 18px; border-bottom: 1px solid var(--border);
           background: var(--surface); flex-shrink: 0; }
  header .logo { font-size: 18px; font-weight: 700; letter-spacing: -.5px; color: var(--accent); }
  header .badge { font-size: 11px; background: var(--border); padding: 2px 7px;
                  border-radius: 99px; color: var(--muted); }
  header .spacer { flex: 1; }
  header .status-dot { width: 8px; height: 8px; border-radius: 50%;
                       background: var(--muted); transition: background .3s; }
  header .status-dot.running { background: var(--green); box-shadow: 0 0 6px var(--green); }

  /* ── Layout ── */
  .workspace { display: grid; grid-template-columns: 340px 1fr 260px;
               flex: 1; overflow: hidden; }

  /* ── Left panel ── */
  .left { display: flex; flex-direction: column; border-right: 1px solid var(--border);
          background: var(--surface); overflow: hidden; }
  .left .section { padding: 14px 16px; border-bottom: 1px solid var(--border); }
  .left .section label { display: block; font-size: 11px; color: var(--muted);
                          text-transform: uppercase; letter-spacing: .08em; margin-bottom: 6px; }
  input, select, textarea {
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    color: var(--text); border-radius: var(--radius); padding: 7px 10px;
    font-size: 13px; font-family: inherit; outline: none; transition: border-color .2s;
  }
  input:focus, select:focus, textarea:focus { border-color: var(--accent); }
  select option { background: var(--bg); }
  .prompt-wrap { flex: 1; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; overflow: hidden; }
  textarea#prompt { flex: 1; resize: none; font-size: 13px; line-height: 1.5; min-height: 120px; }
  button#run-btn, button#stop-btn {
    border: none; border-radius: var(--radius);
    padding: 9px 0; font-size: 14px; font-weight: 600; cursor: pointer;
    transition: opacity .2s; width: 100%;
  }
  button#run-btn {
    background: var(--accent); color: #fff;
  }
  button#stop-btn {
    background: var(--red); color: #fff; display: none;
  }
  button#run-btn:disabled { opacity: .45; cursor: not-allowed; }
  button#run-btn:not(:disabled):hover { opacity: .88; }
  button#stop-btn:hover { opacity: .88; }
  .hint { font-size: 11px; color: var(--muted); text-align: center; }

  /* ── Stream panel ── */
  .stream { display: flex; flex-direction: column; overflow: hidden; }
  .stream-header { padding: 10px 16px; border-bottom: 1px solid var(--border);
                   font-size: 12px; color: var(--muted); display: flex; justify-content: space-between; }
  #stream-body { flex: 1; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
  #stream-body:empty::before { content: 'Agent output will appear here…';
                                color: var(--muted); font-style: italic; }

  /* ── Event cards ── */
  .card { border-radius: var(--radius); padding: 10px 13px; font-size: 13px; line-height: 1.55; }
  .card.thinking { background: #1a1a2e; border-left: 3px solid var(--blue); white-space: pre-wrap; word-break: break-word; }
  .card.tool-call { background: #1e1a0e; border-left: 3px solid var(--orange); }
  .card.tool-result { background: #0e1a10; border-left: 3px solid var(--green); }
  .card.tool-result.error { background: #1a0e0e; border-left-color: var(--red); }
  .card.complete-card { background: #171225; border: 1px solid var(--accent);
                         white-space: pre-wrap; word-break: break-word; }
  .card.error-card { background: #1a0e0e; border-left: 3px solid var(--red); }

  .card .card-label { font-size: 11px; font-weight: 700; text-transform: uppercase;
                       letter-spacing: .08em; margin-bottom: 5px; opacity: .8; }
  .card.thinking .card-label { color: var(--blue); }
  .card.tool-call .card-label { color: var(--orange); }
  .card.tool-result .card-label { color: var(--green); }
  .card.tool-result.error .card-label { color: var(--red); }
  .card.complete-card .card-label { color: var(--accent); }
  .card.error-card .card-label { color: var(--red); }

  .card pre { font-family: var(--font-mono); font-size: 12px; overflow-x: auto;
              white-space: pre-wrap; word-break: break-word; margin-top: 4px; }
  .tool-name { font-family: var(--font-mono); font-weight: 700; color: var(--orange); }
  .copy-btn { float: right; font-size: 11px; background: var(--border); border: none;
              color: var(--muted); border-radius: 4px; padding: 2px 8px; cursor: pointer; }
  .copy-btn:hover { color: var(--text); }

  /* ── Files panel ── */
  .files-panel { border-left: 1px solid var(--border); background: var(--surface);
                  display: flex; flex-direction: column; overflow: hidden; }
  .files-panel .panel-header { padding: 10px 14px; border-bottom: 1px solid var(--border);
                                 font-size: 12px; color: var(--muted); }
  #file-list { flex: 1; overflow-y: auto; padding: 8px 0; }
  .file-item { display: flex; align-items: center; gap: 7px; padding: 5px 14px;
               cursor: pointer; font-size: 12px; border-radius: 0;
               transition: background .15s; }
  .file-item:hover { background: var(--border); }
  .file-item .fi-name { flex: 1; font-family: var(--font-mono); color: var(--text); }
  .file-item .fi-size { font-size: 10px; color: var(--muted); }
  .file-item .fi-icon { font-size: 13px; }

  /* ── File viewer overlay ── */
  .viewer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.7);
                     display: none; align-items: center; justify-content: center; z-index: 100; }
  .viewer-overlay.open { display: flex; }
  .viewer-box { background: var(--surface); border: 1px solid var(--border);
                border-radius: 12px; width: min(90vw, 800px); max-height: 80vh;
                display: flex; flex-direction: column; overflow: hidden; }
  .viewer-box .vb-header { display: flex; align-items: center; padding: 12px 16px;
                            border-bottom: 1px solid var(--border); gap: 10px; }
  .viewer-box .vb-name { flex: 1; font-family: var(--font-mono); font-size: 13px; }
  .viewer-box .vb-close { background: none; border: 1px solid var(--border);
                           color: var(--muted); border-radius: 6px; padding: 3px 10px;
                           cursor: pointer; }
  .viewer-box pre { flex: 1; overflow: auto; padding: 16px; font-family: var(--font-mono);
                    font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }

  /* ── Spinner ── */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid var(--border);
             border-top-color: var(--accent); border-radius: 50%;
             animation: spin .7s linear infinite; vertical-align: middle; margin-right: 5px; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<header>
  <span class="logo">🐼 panda</span>
  <span class="badge">agent workspace</span>
  <span class="spacer"></span>
  <span id="status-label" style="font-size:12px;color:var(--muted)">idle</span>
  <span class="status-dot" id="status-dot"></span>
</header>

<div class="workspace">
  <!-- LEFT: Config + Prompt -->
  <div class="left">
    <div class="section">
      <label>Working Directory</label>
      <input id="workdir" placeholder="leave blank → auto temp dir" />
    </div>
    <div class="section" style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      <div>
        <label>Model</label>
        <select id="model">
          <option value="">default</option>
          <option value="claude-haiku-4-5-20251001">haiku-4-5</option>
          <option value="claude-sonnet-4-5">sonnet-4-5</option>
          <option value="claude-opus-4-5">opus-4-5</option>
          <option value="claude-opus-4-6">opus-4-6</option>
        </select>
      </div>
      <div>
        <label>Mode</label>
        <select id="mode">
          <option value="yolo">yolo</option>
          <option value="safe">safe</option>
          <option value="read-only">read-only</option>
        </select>
      </div>
    </div>
    <div class="prompt-wrap">
      <label style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em">Prompt</label>
      <textarea id="prompt" placeholder="Describe what you want to build…&#10;&#10;e.g. Build a FastAPI hello-world with /health and /echo endpoints, and a test suite."></textarea>
      <button id="run-btn" onclick="startRun()">▶ Run  <kbd style="font-size:10px;opacity:.6">Ctrl+↵</kbd></button>
      <button id="stop-btn" onclick="stopRun()">⏹ Stop Session</button>
      <div class="hint">Files are written to the working directory</div>
    </div>
  </div>

  <!-- CENTER: Stream -->
  <div class="stream">
    <div class="stream-header">
      <span id="stream-title">Live agent stream</span>
      <span id="turn-count"></span>
    </div>
    <div id="stream-body"></div>
  </div>

  <!-- RIGHT: Files -->
  <div class="files-panel">
    <div class="panel-header">Files created</div>
    <div id="file-list"></div>
  </div>
</div>

<!-- File viewer overlay -->
<div class="viewer-overlay" id="viewer" onclick="if(event.target===this)closeViewer()">
  <div class="viewer-box">
    <div class="vb-header">
      <span class="vb-name" id="viewer-name"></span>
      <button class="vb-close" onclick="closeViewer()">✕ close</button>
    </div>
    <pre id="viewer-content"></pre>
  </div>
</div>

<script>
let _es = null;
let _turns = 0;
let _currentRunId = null;

function setStatus(running) {
  document.getElementById('status-dot').classList.toggle('running', running);
  document.getElementById('status-label').textContent = running ? 'running' : 'idle';
  document.getElementById('run-btn').disabled = running;
  document.getElementById('stop-btn').style.display = running ? 'block' : 'none';
}

function card(cls, labelText, bodyHTML) {
  const d = document.createElement('div');
  d.className = 'card ' + cls;
  d.innerHTML = `<div class="card-label">${labelText}</div>${bodyHTML}`;
  return d;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function addCard(el) {
  const body = document.getElementById('stream-body');
  body.appendChild(el);
  body.scrollTop = body.scrollHeight;
}

async function startRun() {
  const task = document.getElementById('prompt').value.trim();
  if (!task) return;

  // clear stream
  document.getElementById('stream-body').innerHTML = '';
  document.getElementById('file-list').innerHTML = '';
  document.getElementById('turn-count').textContent = '';
  _turns = 0;
  if (_es) { _es.close(); _es = null; }

  setStatus(true);

  const body = {
    task,
    workdir: document.getElementById('workdir').value.trim(),
    model:   document.getElementById('model').value,
    mode:    document.getElementById('mode').value,
  };

  let run_id, workdir;
  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    run_id  = data.run_id;
    workdir = data.workdir;
    _currentRunId = run_id;
    document.getElementById('workdir').value = workdir;
    document.getElementById('stream-title').textContent = `Run · ${workdir}`;
  } catch(e) {
    addCard(card('error-card', '⚠ Error', `<pre>${escHtml(e.message)}</pre>`));
    setStatus(false);
    return;
  }

  _es = new EventSource(`/api/stream/${run_id}`);

  _es.addEventListener('thinking', e => {
    const d = JSON.parse(e.data);
    if (!d.text) return;
    _turns++;
    document.getElementById('turn-count').textContent = `${_turns} turns`;
    const c = card('thinking', '💭 thinking',
      `<button class="copy-btn" onclick="navigator.clipboard.writeText(this.dataset.t)" data-t="${escHtml(d.text)}">copy</button><pre>${escHtml(d.text)}</pre>`);
    addCard(c);
  });

  _es.addEventListener('tool_call', e => {
    const d = JSON.parse(e.data);
    const argsHtml = Object.entries(d.args||{}).map(([k,v]) =>
      `  <span style="color:var(--muted)">${escHtml(k)}</span>=${escHtml(v)}`
    ).join('\n');
    addCard(card('tool-call', `🔧 <span class="tool-name">${escHtml(d.name)}</span>`,
      `<pre>${argsHtml || '(no args)'}</pre>`));
  });

  _es.addEventListener('tool_result', e => {
    const d = JSON.parse(e.data);
    const cls = d.ok ? 'tool-result' : 'tool-result error';
    const icon = d.ok ? '✅' : '❌';
    addCard(card(cls, `${icon} ${escHtml(d.name)}`,
      `<pre>${escHtml(d.result)}</pre>`));
  });

  _es.addEventListener('complete', e => {
    const d = JSON.parse(e.data);
    const c = card('complete-card', '✨ complete',
      `<button class="copy-btn" onclick="navigator.clipboard.writeText(this.dataset.t)" data-t="${escHtml(d.text)}">copy</button><pre>${escHtml(d.text)}</pre>`);
    addCard(c);
    renderFiles(d.files || []);
    setStatus(false);
    _es.close();
  });

  _es.addEventListener('error', e => {
    try {
      const d = JSON.parse(e.data);
      addCard(card('error-card', '⚠ error', `<pre>${escHtml(d.message)}</pre>`));
    } catch(_) {}
    setStatus(false);
    _es.close();
  });

  _es.onerror = () => setStatus(false);
}

function renderFiles(files) {
  const list = document.getElementById('file-list');
  list.innerHTML = '';
  const icons = {html:'🌐', py:'🐍', js:'📜', ts:'📜', json:'📋',
                 md:'📝', css:'🎨', txt:'📄', sh:'⚙️'};
  files.forEach(f => {
    const ext = f.name.split('.').pop().toLowerCase();
    const icon = icons[ext] || '📄';
    const sz = f.size > 1024 ? `${(f.size/1024).toFixed(1)}k` : `${f.size}b`;
    const item = document.createElement('div');
    item.className = 'file-item';
    item.innerHTML = `<span class="fi-icon">${icon}</span><span class="fi-name">${escHtml(f.rel)}</span><span class="fi-size">${sz}</span>`;
    item.onclick = () => openFile(f.path, f.name);
    list.appendChild(item);
  });
}

async function openFile(path, name) {
  const r = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
  const text = await r.text();
  document.getElementById('viewer-name').textContent = name;
  document.getElementById('viewer-content').textContent = text;
  document.getElementById('viewer').classList.add('open');
}

function closeViewer() {
  document.getElementById('viewer').classList.remove('open');
}

async function stopRun() {
  if (!_currentRunId) return;
  
  try {
    const r = await fetch(`/api/stop/${_currentRunId}`, {
      method: 'POST',
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    addCard(card('complete-card', '⏹ stopped', `<pre>Session stopped by user</pre>`));
  } catch(e) {
    addCard(card('error-card', '⚠ Error', `<pre>${escHtml(e.message)}</pre>`));
  }
  
  if (_es) { _es.close(); _es = null; }
  setStatus(false);
  _currentRunId = null;
}

document.getElementById('prompt').addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') startRun();
});
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Panda web UI")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    url = f"http://localhost:{args.port}"
    print(f"\n  🐼  panda UI  →  {url}\n")

    if not args.no_open:
        try:
            import webbrowser, threading
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        except Exception:
            pass

    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()