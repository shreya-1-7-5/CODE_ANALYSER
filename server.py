# server.py
import os
import re
import json
from flask import Flask, request, jsonify, render_template_string
import ast

app = Flask(__name__)

# ---------------------------
# PYTHON CODE ANALYSIS
# ---------------------------

def python_unused_imports(code):
    try:
        tree = ast.parse(code)
    except Exception:
        return {"error": "syntax error"}

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imported.add(n.asname or n.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for n in node.names:
                imported.add(n.asname or n.name)

    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                used.add(node.value.id)

    unused = sorted([name for name in imported if name not in used])
    return {"unused_imports": unused}

class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.func_complexities = {}
        self.current = None

    def _inc(self):
        if self.current:
            self.func_complexities[self.current] += 1

    def visit_FunctionDef(self, node):
        name = f"{node.name}@{node.lineno}"
        self.current = name
        self.func_complexities[name] = 1
        self.generic_visit(node)
        self.current = None

    def visit_If(self, node):
        self._inc(); self.generic_visit(node)

    def visit_For(self, node):
        self._inc(); self.generic_visit(node)

    def visit_While(self, node):
        self._inc(); self.generic_visit(node)

    def visit_Try(self, node):
        self._inc(); self.generic_visit(node)

    def visit_With(self, node):
        self._inc(); self.generic_visit(node)

    def visit_BoolOp(self, node):
        self._inc(); self.generic_visit(node)

def python_function_info(code):
    try:
        tree = ast.parse(code)
    except Exception:
        return {"error": "syntax error"}

    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            start = node.lineno
            end = getattr(node, 'end_lineno', start)
            length = (end - start + 1) if (start and end) else None
            funcs.append({
                "name": node.name,
                "start_line": start,
                "end_line": end,
                "length": length
            })

    vis = ComplexityVisitor()
    vis.visit(tree)

    for f in funcs:
        key = f"{f['name']}@{f['start_line']}"
        f["complexity"] = vis.func_complexities.get(key, 1)

    # sort functions by complexity desc then length
    funcs = sorted(funcs, key=lambda x: (-x.get('complexity',0), - (x.get('length') or 0)))
    return {"functions": funcs, "function_count": len(funcs)}

def python_file_stats(code):
    lines = code.splitlines()
    todo_count = sum(1 for l in lines if "TODO" in l.upper())
    return {"lines": len(lines), "todos": todo_count, "long_file": len(lines) > 800}

def analyze_python(code):
    result = {}
    result.update(python_unused_imports(code))
    result.update(python_function_info(code))
    result.update(python_file_stats(code))
    return result

# ---------------------------
# JS CODE ANALYSIS
# ---------------------------

JS_FUNC_RE = re.compile(r'(function\s+([A-Za-z0-9_$]+)\s*\()|([A-Za-z0-9_$]+\s*=\s*\([^\)]*\)\s*=>)')

def analyze_js(code):
    lines = code.splitlines()
    todo_count = sum(1 for l in lines if "TODO" in l.upper())
    funcs = []
    line_count = len(lines)

    for match in JS_FUNC_RE.finditer(code):
        pos = match.start()
        start_line = code[:pos].count("\n") + 1
        funcs.append({"start_line": start_line})

    long_file = line_count > 1200
    long_funcs = [f for f in funcs if (line_count - f['start_line']) >= 100]  # rough approx

    return {
        "lines": line_count,
        "todos": todo_count,
        "function_count": len(funcs),
        "long_functions": long_funcs,
        "long_file": long_file
    }

# ---------------------------
# API ENDPOINT
# ---------------------------

@app.route('/api/analyze', methods=['POST'])
def analyze():
    output = []
    files = request.files.getlist("files")

    if not files:
        return jsonify({"error": "no files uploaded"}), 400

    for f in files:
        filename = f.filename
        code = f.read().decode("utf-8", errors="replace")
        ext = os.path.splitext(filename)[1].lower()

        if ext == ".py":
            result = analyze_python(code)
            kind = "python"
        elif ext == ".js":
            result = analyze_js(code)
            kind = "javascript"
        else:
            result = {"lines": len(code.splitlines())}
            kind = "unknown"

        # add quick summary tags for UI highlight
        tags = []
        if result.get("lines",0) > 800:
            tags.append("Long file")
        if kind == "python":
            funcs = result.get("functions", [])
            if any(f.get("length",0) >= 120 for f in funcs):
                tags.append("Long functions")
            if any(f.get("complexity",0) >= 12 for f in funcs):
                tags.append("High complexity")
            if result.get("unused_imports"):
                tags.append("Unused imports")
            if result.get("todos",0) > 0:
                tags.append("TODOs")
        elif kind == "javascript":
            if result.get("long_file"):
                tags.append("Long file")
            if result.get("long_functions"):
                tags.append("Long functions")
            if result.get("todos",0) > 0:
                tags.append("TODOs")

        output.append({
            "filename": filename,
            "kind": kind,
            "analysis": result,
            "tags": tags
        })

    return jsonify({"results": output})

# ---------------------------
# STYLISH GREEN/BLACK UI
# ---------------------------

HTML_PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Code Quality Analyzer — Green / Black UI</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    :root{
      --bg: #06110a;
      --panel: #0b1a13;
      --muted: #9fdac1;
      --accent: #2aff7f;
      --danger: #ff5c5c;
      --card: linear-gradient(180deg, rgba(10,30,20,0.9), rgba(6,17,10,0.9));
      --glass: rgba(255,255,255,0.03);
      --radius: 10px;
    }
    html,body{height:100%;margin:0;background:var(--bg);color:var(--muted);font-family:Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;}
    .wrap{max-width:1100px;margin:24px auto;padding:20px;}
    header{display:flex;align-items:center;gap:16px;margin-bottom:18px;}
    .logo{width:56px;height:56px;border-radius:12px;background:radial-gradient(circle at 30% 30%, #00ff9b, #007a3d);display:flex;align-items:center;justify-content:center;font-weight:700;color:#01240f;font-size:20px;box-shadow:0 6px 18px rgba(0,0,0,0.6);}
    h1{margin:0;font-size:20px;color:var(--accent);}
    p.lead{margin:0;color:#aee6c8;font-size:13px}
    .upload{display:flex;gap:12px;align-items:center;margin-top:14px;}
    input[type=file]{background:var(--panel); color:var(--muted); padding:8px 10px; border-radius:8px; border:1px solid rgba(255,255,255,0.04);}
    button.btn{background:linear-gradient(90deg,#00d775,#00ff9b); color:#01240f; border:none; padding:10px 14px; border-radius:10px; cursor:pointer; font-weight:600; box-shadow:0 6px 20px rgba(0,255,150,0.06);}
    button.btn:active{transform:translateY(1px)}
    .status{margin-left:12px;font-size:13px;color:#bfeed7}
    .grid{display:grid;grid-template-columns: 1fr 320px; gap:18px;margin-top:18px;}
    .panel{background:var(--panel); border-radius:var(--radius); padding:14px; box-shadow: 0 6px 30px rgba(0,0,0,0.6);}
    .results{display:flex;flex-direction:column;gap:12px; max-height:70vh; overflow:auto; padding-right:6px;}
    .file-card{background:var(--card);border-radius:8px;padding:12px;border:1px solid rgba(255,255,255,0.03); box-shadow: 0 8px 30px rgba(0,0,0,0.6);}
    .file-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px;}
    .fname{font-weight:700;color:var(--accent);}
    .badge{display:inline-block;padding:6px 8px;border-radius:999px;background:rgba(0,0,0,0.28);color:var(--muted);font-weight:600;font-size:12px}
    .tag{display:inline-block;padding:6px 8px;border-radius:999px;background:rgba(45,255,127,0.12);color:var(--accent);font-weight:700;margin-left:8px;font-size:12px;border:1px solid rgba(45,255,127,0.08)}
    .warn{background:rgba(255,90,90,0.08); color:var(--danger); border:1px solid rgba(255,90,90,0.08)}
    table{width:100%;border-collapse:collapse;margin-top:8px}
    th,td{padding:8px 6px;text-align:left;font-size:13px;color:var(--muted);border-bottom:1px dashed rgba(255,255,255,0.03)}
    th{color:#c8f9d4;font-size:12px;font-weight:700}
    .small{font-size:12px;color:#9de2b8}
    .pill{display:inline-block;padding:6px 8px;border-radius:999px;background:#062b1d;color:var(--accent);font-weight:700;font-size:12px;border:1px solid rgba(0,255,127,0.06)}
    .center{display:flex;align-items:center;gap:8px}
    .empty{color:#7eaea0;padding:20px;border-radius:8px;background:rgba(255,255,255,0.02);text-align:center}
    /* responsive */
    @media (max-width:900px){
      .grid{grid-template-columns: 1fr; }
      .results{max-height:50vh}
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="logo">CQ</div>
      <div>
        <h1>Code Quality Analyzer</h1>
        <p class="lead">Upload <strong>.py</strong> or <strong>.js</strong> files. The tool highlights unused imports, long functions/files, TODOs and complexity warnings.</p>
      </div>
    </header>

    <div class="upload">
      <input id="files" type="file" multiple />
      <button id="analyzeBtn" class="btn">Analyze Files</button>
      <div id="status" class="status">No files selected</div>
    </div>

    <div class="grid">
      <div class="panel">
        <h3 style="margin-top:0;color:var(--accent)">Analysis Results</h3>
        <div id="results" class="results">
          <div class="empty">Upload files and click <span class="pill">Analyze Files</span> to start.</div>
        </div>
      </div>

      <div class="panel">
        <h3 style="margin-top:0;color:var(--accent)">Summary</h3>
        <div style="margin-top:8px">
          <div class="center" style="justify-content:space-between">
            <div>
              <div class="small">Files analyzed</div>
              <div id="summaryFiles" class="fname">0</div>
            </div>
            <div>
              <div class="small">Total TODOs</div>
              <div id="summaryTodos" class="fname">0</div>
            </div>
            <div>
              <div class="small">Warnings</div>
              <div id="summaryWarn" class="fname">0</div>
            </div>
          </div>
        </div>

        <hr style="border:none;border-top:1px dashed rgba(255,255,255,0.03);margin:12px 0" />
        <div>
          <h4 style="margin:6px 0;color:var(--accent)">Legend</h4>
          <div style="display:flex;flex-direction:column;gap:8px">
            <div><span class="tag">Unused imports</span> — Python imports never referenced.</div>
            <div><span class="tag" style="background:rgba(255,90,90,0.08;color:var(--danger);border:1px solid rgba(255,90,90,0.06)">High complexity</span> — function has high cyclomatic-like score.</div>
            <div><span class="tag">Long file / function</span> — file or function exceeds length threshold.</div>
          </div>
        </div>
      </div>
    </div>

  </div>

<script>
const analyzeBtn = document.getElementById('analyzeBtn');
const filesInput = document.getElementById('files');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');
const summaryFiles = document.getElementById('summaryFiles');
const summaryTodos = document.getElementById('summaryTodos');
const summaryWarn = document.getElementById('summaryWarn');

function makeBadge(text, cls='badge'){ return '<span class="badge">'+text+'</span>'; }
function makeTag(text){ return '<span class="tag">'+text+'</span>'; }

analyzeBtn.addEventListener('click', async () => {
  const files = filesInput.files;
  if (!files || files.length === 0) { alert('Choose one or more files'); return; }

  statusEl.innerText = 'Uploading and analyzing...';
  resultsEl.innerHTML = '';

  const fd = new FormData();
  for (const f of files) fd.append('files', f);

  try {
    const res = await fetch('/api/analyze', { method: 'POST', body: fd });
    if (!res.ok) {
      const txt = await res.text();
      statusEl.innerText = 'Error: ' + txt;
      return;
    }
    const data = await res.json();
    renderResults(data.results);
    statusEl.innerText = 'Analysis complete';
  } catch (e) {
    statusEl.innerText = 'Network error';
    console.error(e);
  }
});

function renderResults(results){
  resultsEl.innerHTML = '';
  let totalTodos = 0;
  let warnCount = 0;

  if (!results || results.length === 0) {
    resultsEl.innerHTML = '<div class="empty">No results</div>';
    summaryFiles.innerText = '0';
    summaryTodos.innerText = '0';
    summaryWarn.innerText = '0';
    return;
  }

  summaryFiles.innerText = results.length;

  results.forEach(r => {
    const card = document.createElement('div');
    card.className = 'file-card';

    const tagsHtml = (r.tags || []).map(t => `<span class="tag">${t}</span>`).join(' ');
    if ((r.analysis && r.analysis.todos) || 0) totalTodos += r.analysis.todos;

    let warnings = (r.tags || []).length;
    warnCount += warnings;

    let header = `<div class="file-head"><div><div class="fname">${r.filename}</div><div class="small">${r.kind}</div></div><div>${tagsHtml}</div></div>`;

    let body = '';

    if (r.kind === 'python'){
      const a = r.analysis;
      // unused imports
      const unused = (a.unused_imports || []);
      let unusedHtml = unused.length ? `<div style="margin-top:8px"><strong style="color:#bfffdc">Unused imports:</strong> ${unused.map(u=>'<span class="badge">'+u+'</span>').join(' ')}</div>` : '';

      // file stats
      body += `<div class="small">Lines: <strong>${a.lines}</strong> &nbsp; • &nbsp; TODOs: <strong>${a.todos}</strong></div>`;
      // functions table
      const funcs = a.functions || [];
      if (funcs.length){
        let rows = '<table><thead><tr><th>Function</th><th>Length</th><th>Complexity</th></tr></thead><tbody>';
        funcs.forEach(f => {
          let comp = f.complexity || 0;
          let length = f.length || '-';
          let compClass = comp >= 12 ? 'warn' : '';
          rows += `<tr><td>${f.name} <span class="small">@${f.start_line}</span></td><td>${length}</td><td class="${compClass}">${comp}</td></tr>`;
        });
        rows += '</tbody></table>';
        body += rows;
      } else {
        body += `<div class="small" style="margin-top:6px">No functions detected</div>`;
      }

      body += unusedHtml;

    } else if (r.kind === 'javascript'){
      const a = r.analysis;
      body += `<div class="small">Lines: <strong>${a.lines}</strong> &nbsp; • &nbsp; TODOs: <strong>${a.todos}</strong> &nbsp; • &nbsp; Functions: <strong>${a.function_count}</strong></div>`;
      if (a.long_functions && a.long_functions.length){
        body += `<div style="margin-top:8px"><strong class="small">Long functions detected:</strong> ${a.long_functions.length}</div>`;
      }
    } else {
      body += `<div class="small">Lines: <strong>${r.analysis.lines || 0}</strong></div>`;
    }

    card.innerHTML = header + body;
    resultsEl.appendChild(card);
  });

  summaryTodos.innerText = totalTodos;
  summaryWarn.innerText = warnCount;
}
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

if __name__ == "__main__":
    app.run(debug=True)
# server.py
import os
import re
import json
from flask import Flask, request, jsonify, render_template_string
import ast

app = Flask(__name__)

# ---------------------------
# PYTHON CODE ANALYSIS
# ---------------------------

def python_unused_imports(code):
    try:
        tree = ast.parse(code)
    except Exception:
        return {"error": "syntax error"}

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imported.add(n.asname or n.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for n in node.names:
                imported.add(n.asname or n.name)

    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                used.add(node.value.id)

    unused = sorted([name for name in imported if name not in used])
    return {"unused_imports": unused}

class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.func_complexities = {}
        self.current = None

    def _inc(self):
        if self.current:
            self.func_complexities[self.current] += 1

    def visit_FunctionDef(self, node):
        name = f"{node.name}@{node.lineno}"
        self.current = name
        self.func_complexities[name] = 1
        self.generic_visit(node)
        self.current = None

    def visit_If(self, node):
        self._inc(); self.generic_visit(node)

    def visit_For(self, node):
        self._inc(); self.generic_visit(node)

    def visit_While(self, node):
        self._inc(); self.generic_visit(node)

    def visit_Try(self, node):
        self._inc(); self.generic_visit(node)

    def visit_With(self, node):
        self._inc(); self.generic_visit(node)

    def visit_BoolOp(self, node):
        self._inc(); self.generic_visit(node)

def python_function_info(code):
    try:
        tree = ast.parse(code)
    except Exception:
        return {"error": "syntax error"}

    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            start = node.lineno
            end = getattr(node, 'end_lineno', start)
            length = (end - start + 1) if (start and end) else None
            funcs.append({
                "name": node.name,
                "start_line": start,
                "end_line": end,
                "length": length
            })

    vis = ComplexityVisitor()
    vis.visit(tree)

    for f in funcs:
        key = f"{f['name']}@{f['start_line']}"
        f["complexity"] = vis.func_complexities.get(key, 1)

    # sort functions by complexity desc then length
    funcs = sorted(funcs, key=lambda x: (-x.get('complexity',0), - (x.get('length') or 0)))
    return {"functions": funcs, "function_count": len(funcs)}

def python_file_stats(code):
    lines = code.splitlines()
    todo_count = sum(1 for l in lines if "TODO" in l.upper())
    return {"lines": len(lines), "todos": todo_count, "long_file": len(lines) > 800}

def analyze_python(code):
    result = {}
    result.update(python_unused_imports(code))
    result.update(python_function_info(code))
    result.update(python_file_stats(code))
    return result

# ---------------------------
# JS CODE ANALYSIS
# ---------------------------

JS_FUNC_RE = re.compile(r'(function\s+([A-Za-z0-9_$]+)\s*\()|([A-Za-z0-9_$]+\s*=\s*\([^\)]*\)\s*=>)')

def analyze_js(code):
    lines = code.splitlines()
    todo_count = sum(1 for l in lines if "TODO" in l.upper())
    funcs = []
    line_count = len(lines)

    for match in JS_FUNC_RE.finditer(code):
        pos = match.start()
        start_line = code[:pos].count("\n") + 1
        funcs.append({"start_line": start_line})

    long_file = line_count > 1200
    long_funcs = [f for f in funcs if (line_count - f['start_line']) >= 100]  # rough approx

    return {
        "lines": line_count,
        "todos": todo_count,
        "function_count": len(funcs),
        "long_functions": long_funcs,
        "long_file": long_file
    }

# ---------------------------
# API ENDPOINT
# ---------------------------

@app.route('/api/analyze', methods=['POST'])
def analyze():
    output = []
    files = request.files.getlist("files")

    if not files:
        return jsonify({"error": "no files uploaded"}), 400

    for f in files:
        filename = f.filename
        code = f.read().decode("utf-8", errors="replace")
        ext = os.path.splitext(filename)[1].lower()

        if ext == ".py":
            result = analyze_python(code)
            kind = "python"
        elif ext == ".js":
            result = analyze_js(code)
            kind = "javascript"
        else:
            result = {"lines": len(code.splitlines())}
            kind = "unknown"

        # add quick summary tags for UI highlight
        tags = []
        if result.get("lines",0) > 800:
            tags.append("Long file")
        if kind == "python":
            funcs = result.get("functions", [])
            if any(f.get("length",0) >= 120 for f in funcs):
                tags.append("Long functions")
            if any(f.get("complexity",0) >= 12 for f in funcs):
                tags.append("High complexity")
            if result.get("unused_imports"):
                tags.append("Unused imports")
            if result.get("todos",0) > 0:
                tags.append("TODOs")
        elif kind == "javascript":
            if result.get("long_file"):
                tags.append("Long file")
            if result.get("long_functions"):
                tags.append("Long functions")
            if result.get("todos",0) > 0:
                tags.append("TODOs")

        output.append({
            "filename": filename,
            "kind": kind,
            "analysis": result,
            "tags": tags
        })

    return jsonify({"results": output})





@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

if __name__ == "__main__":
    app.run(debug=True)
