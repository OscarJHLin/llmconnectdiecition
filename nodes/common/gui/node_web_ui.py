#!/usr/bin/env python3
"""
NetConnect Node Web UI
A browser-based installer and dashboard for network/compute sub-nodes.
Runs a local web server that can be accessed at http://localhost:8080
"""

import sys
import os
import socket
import json
import asyncio
import threading
import time
import uuid
from datetime import datetime
from typing import Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from central.ai.model_adapter import ModelAdapter, ModelBackend
from nodes.common.compute.hermes_node import HermesComputeNode

BACKEND_PORTS = {
    "Ollama": 11434,
    "vLLM": 8000,
    "LM Studio": 1234,
    "OpenAI": 443,
}

BACKEND_ENUM_MAP = {
    "Ollama": ModelBackend.OLLAMA,
    "vLLM": ModelBackend.VLLM,
    "LM Studio": ModelBackend.LM_STUDIO,
    "OpenAI": ModelBackend.OPENAI,
}

# Global state
_app_state = {
    "ai_adapter": None,
    "hermes_node": None,
    "network_client": None,
    "config": {
        "backend": "Hermes",
        "url": "http://localhost",
        "port": 11434,
        "model": "",
        "node_name": f"node-{uuid.uuid4().hex[:6]}",
        "multicast_group": "224.0.0.1",
        "multicast_port": 5000,
    },
    "status": {
        "ai_connected": False,
        "network_connected": False,
        "node_running": False,
        "task_status": "idle",
        "tasks_completed": 0,
    },
    "logs": [],
    "chat_history": [],
}


def _log(message: str):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {message}"
    _app_state["logs"].append(entry)
    if len(_app_state["logs"]) > 200:
        _app_state["logs"] = _app_state["logs"][-200:]
    print(entry)


class AsyncRunner:
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._start()

    def _start(self):
        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()
        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
        while self.loop is None:
            time.sleep(0.01)

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


_runner = AsyncRunner()


HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NetConnect Node Installer</title>
<style>
:root {
  --bg: #1e1e2e;
  --fg: #cdd6f4;
  --accent: #89b4fa;
  --success: #a6e3a1;
  --warning: #f9e2af;
  --error: #f38ba8;
  --surface: #313244;
  --border: #585b70;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.6;
}
.container { max-width: 960px; margin: 0 auto; padding: 20px; }
header {
  background: var(--surface);
  padding: 20px;
  border-radius: 12px;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
header h1 { margin: 0; font-size: 1.5rem; }
.step-indicator { color: var(--accent); font-weight: bold; }
.card {
  background: var(--surface);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 20px;
  border: 1px solid var(--border);
}
.card h2 { margin-top: 0; font-size: 1.2rem; color: var(--accent); }
.form-row { display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 15px; align-items: center; }
.form-row label { min-width: 120px; font-weight: 500; }
input, select {
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 14px;
  flex: 1;
  min-width: 200px;
}
input:focus, select:focus { outline: none; border-color: var(--accent); }
button {
  background: var(--accent);
  color: var(--bg);
  border: none;
  border-radius: 6px;
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}
button:hover { opacity: 0.85; }
button.secondary {
  background: var(--surface);
  color: var(--fg);
  border: 1px solid var(--border);
}
button:disabled { opacity: 0.5; cursor: not-allowed; }
.badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}
.badge.success { background: var(--success); color: var(--bg); }
.badge.error { background: var(--error); color: var(--bg); }
.badge.warning { background: var(--warning); color: var(--bg); }
.badge.info { background: var(--accent); color: var(--bg); }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
@media (max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
.status-card {
  background: var(--bg);
  border-radius: 8px;
  padding: 15px;
}
.status-card h3 { margin: 0 0 10px 0; font-size: 0.9rem; color: var(--border); }
.status-value { font-size: 1.1rem; font-weight: 600; }
.log-panel {
  background: var(--bg);
  border-radius: 8px;
  padding: 15px;
  height: 250px;
  overflow-y: auto;
  font-family: "SF Mono", Monaco, "Cascadia Code", monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}
.chat-panel {
  background: var(--bg);
  border-radius: 8px;
  padding: 15px;
  height: 300px;
  overflow-y: auto;
  margin-bottom: 10px;
}
.chat-msg { margin-bottom: 10px; }
.chat-msg .role { font-weight: 600; font-size: 12px; }
.chat-msg.user .role { color: var(--accent); }
.chat-msg.assistant .role { color: var(--success); }
.chat-msg.system .role { color: var(--border); }
.chat-input-row { display: flex; gap: 10px; }
.chat-input-row input { flex: 1; }
.nav-buttons { display: flex; justify-content: space-between; margin-top: 20px; }
.hidden { display: none; }
.scan-result { margin-top: 10px; padding: 10px; background: var(--bg); border-radius: 6px; font-size: 13px; }
.tabs { display: flex; gap: 5px; margin-bottom: 15px; }
.tab-btn {
  background: var(--surface);
  color: var(--fg);
  border: 1px solid var(--border);
  padding: 8px 16px;
  border-radius: 6px 6px 0 0;
}
.tab-btn.active { background: var(--accent); color: var(--bg); border-color: var(--accent); }
.tab-content { display: none; }
.tab-content.active { display: block; }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>NetConnect Node Installer</h1>
    <span class="step-indicator" id="stepIndicator">Step 1 of 3: AI Backend</span>
  </header>

  <!-- Step 1: AI Backend -->
  <div id="step1" class="card">
    <h2>Select AI Backend</h2>
    <div class="form-row">
      <label>Backend:</label>
      <select id="backendSelect">
        <option>Ollama</option>
        <option>vLLM</option>
        <option>LM Studio</option>
        <option>OpenAI</option>
      </select>
      <button type="button" onclick="autoScan()">Auto-Scan</button>
    </div>
    <div class="form-row">
      <label>Base URL:</label>
      <input type="text" id="backendUrl" value="http://localhost">
    </div>
    <div class="form-row">
      <label>Port:</label>
      <input type="number" id="backendPort" value="11434">
    </div>
    <div class="form-row">
      <label>Model:</label>
      <input type="text" id="backendModel" placeholder="Leave empty for auto-detect">
    </div>
    <div class="form-row">
      <label>Status:</label>
      <span id="aiStatusBadge" class="badge warning">Not tested</span>
    </div>
    <div id="scanResult" class="scan-result hidden"></div>
    <button type="button" onclick="testAI()">Test AI Connection</button>
  </div>

  <!-- Step 2: Network -->
  <div id="step2" class="card hidden">
    <h2>Network Configuration</h2>
    <div class="form-row">
      <label>Node Name:</label>
      <input type="text" id="nodeName" value="" placeholder="node-abc123">
    </div>
    <div class="form-row">
      <label>Multicast Group:</label>
      <input type="text" id="multicastGroup" value="224.0.0.1">
    </div>
    <div class="form-row">
      <label>Multicast Port:</label>
      <input type="number" id="multicastPort" value="5000">
    </div>
    <div class="form-row">
      <label>Status:</label>
      <span id="netStatusBadge" class="badge warning">Not configured</span>
    </div>
    <p style="color: var(--border); font-size: 13px;">
      The node will use multicast to discover the central router. Ensure your network allows UDP multicast traffic.
    </p>
  </div>

  <!-- Step 3: Dashboard -->
  <div id="step3" class="card hidden">
    <h2>Node Dashboard</h2>
    <div class="form-row">
      <button id="startBtn" type="button" onclick="startNode()">Start Node</button>
      <button id="stopBtn" type="button" class="secondary" onclick="stopNode()" disabled>Stop Node</button>
      <span id="nodeStatusBadge" class="badge error">Stopped</span>
    </div>

    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('dash')">Dashboard</button>
      <button class="tab-btn" onclick="switchTab('chat')">Chat</button>
      <button class="tab-btn" onclick="switchTab('logs')">Logs</button>
    </div>

    <div id="tab-dash" class="tab-content active">
      <div class="grid-2">
        <div class="status-card">
          <h3>Connection</h3>
          <div class="status-value" id="dashRouter">Not discovered</div>
          <div style="margin-top:8px; font-size:13px; color:var(--border);">Connected Nodes: <span id="dashNodes">0</span></div>
        </div>
        <div class="status-card">
          <h3>AI Backend</h3>
          <div class="status-value" id="dashBackend">-</div>
          <div style="margin-top:8px; font-size:13px; color:var(--border);">Model: <span id="dashModel">-</span></div>
          <div style="margin-top:4px;"><span id="dashAIStatus" class="badge warning">Unknown</span></div>
        </div>
        <div class="status-card">
          <h3>Tasks</h3>
          <div class="status-value" id="dashTaskStatus">Idle</div>
          <div style="margin-top:8px; font-size:13px; color:var(--border);">Completed: <span id="dashCompleted">0</span></div>
        </div>
        <div class="status-card">
          <h3>Node Info</h3>
          <div class="status-value" id="dashNodeName" style="font-size:14px;">-</div>
          <div style="margin-top:8px; font-size:12px; color:var(--border); word-break:break-all;" id="dashNodeId">-</div>
        </div>
      </div>
    </div>

    <div id="tab-chat" class="tab-content">
      <div class="chat-panel" id="chatPanel"></div>
      <div class="chat-input-row">
        <input type="text" id="chatInput" placeholder="Type a message..." onkeypress="if(event.key==='Enter')sendChat()">
        <button onclick="sendChat()">Send</button>
      </div>
    </div>

    <div id="tab-logs" class="tab-content">
      <div class="log-panel" id="logPanel">Waiting for logs...</div>
    </div>
  </div>

  <div class="nav-buttons">
    <button class="secondary" id="backBtn" onclick="prevStep()" disabled>Back</button>
    <button id="nextBtn" onclick="nextStep()">Next</button>
  </div>
</div>

<script>
let currentStep = 1;
const totalSteps = 3;

function showStep(n) {
  for (let i = 1; i <= totalSteps; i++) {
    document.getElementById('step' + i).classList.toggle('hidden', i !== n);
  }
  currentStep = n;
  document.getElementById('stepIndicator').textContent = 'Step ' + n + ' of 3: ' + ['AI Backend','Network','Start Node'][n-1];
  document.getElementById('backBtn').disabled = n === 1;
  if (n === 3) {
    document.getElementById('nextBtn').textContent = 'Finish';
    document.getElementById('nextBtn').disabled = true;
  } else {
    document.getElementById('nextBtn').textContent = 'Next';
    document.getElementById('nextBtn').disabled = false;
  }
}

function nextStep() { if (currentStep < totalSteps) showStep(currentStep + 1); }
function prevStep() { if (currentStep > 1) showStep(currentStep - 1); }

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

async function api(action, data = {}) {
  const res = await fetch('/api', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action, ...data})
  });
  return res.json();
}

async function autoScan() {
  const el = document.getElementById('scanResult');
  el.classList.remove('hidden');
  el.textContent = 'Scanning...';
  const result = await api('auto_scan');
  el.innerHTML = result.results.map(r => {
    const icon = r.ok ? '&#9989;' : '&#10060;';
    return icon + ' ' + r.name + ' (port ' + r.port + '): ' + r.info;
  }).join('<br>');
  if (result.found) {
    document.getElementById('backendSelect').value = result.found;
    document.getElementById('backendPort').value = result.port;
    if (result.model) {
      document.getElementById('backendModel').value = result.model;
    }
    setAIStatus('Auto-selected ' + result.found + (result.model ? ' (' + result.model + ')' : ''), 'success');
  } else {
    setAIStatus('No backend found', 'error');
  }
}

async function testAI() {
  setAIStatus('Testing...', 'info');
  const result = await api('test_ai', {
    backend: document.getElementById('backendSelect').value,
    url: document.getElementById('backendUrl').value,
    port: parseInt(document.getElementById('backendPort').value),
    model: document.getElementById('backendModel').value,
  });
  if (result.ok) {
    setAIStatus('Connected | Models: ' + result.models, 'success');
    if (result.model && !document.getElementById('backendModel').value) {
      document.getElementById('backendModel').value = result.model;
    }
  } else {
    setAIStatus('Connection failed', 'error');
  }
}

function setAIStatus(text, cls) {
  const el = document.getElementById('aiStatusBadge');
  el.textContent = text;
  el.className = 'badge ' + cls;
}

async function startNode() {
  document.getElementById('startBtn').disabled = true;
  setNodeStatus('Starting...', 'info');
  const result = await api('start_node', {
    backend: document.getElementById('backendSelect').value,
    url: document.getElementById('backendUrl').value,
    port: parseInt(document.getElementById('backendPort').value),
    model: document.getElementById('backendModel').value,
    node_name: document.getElementById('nodeName').value || undefined,
    multicast_group: document.getElementById('multicastGroup').value,
    multicast_port: parseInt(document.getElementById('multicastPort').value),
  });
  if (result.ok) {
    setNodeStatus('Running', 'success');
    document.getElementById('stopBtn').disabled = false;
    startPolling();
  } else {
    setNodeStatus('Error: ' + result.error, 'error');
    document.getElementById('startBtn').disabled = false;
  }
}

async function stopNode() {
  document.getElementById('stopBtn').disabled = true;
  setNodeStatus('Stopping...', 'warning');
  await api('stop_node');
  setNodeStatus('Stopped', 'error');
  document.getElementById('startBtn').disabled = false;
}

function setNodeStatus(text, cls) {
  const el = document.getElementById('nodeStatusBadge');
  el.textContent = text;
  el.className = 'badge ' + cls;
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;
  appendChat('user', text);
  input.value = '';
  appendChat('system', 'Thinking...');
  const result = await api('chat', {message: text});
  removeThinking();
  appendChat('assistant', result.response || '[Error]');
}

function appendChat(role, text) {
  const panel = document.getElementById('chatPanel');
  const div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  div.innerHTML = '<div class="role">' + role.toUpperCase() + '</div><div>' + escapeHtml(text) + '</div>';
  panel.appendChild(div);
  panel.scrollTop = panel.scrollHeight;
}

function removeThinking() {
  const panel = document.getElementById('chatPanel');
  const msgs = panel.querySelectorAll('.chat-msg.system');
  if (msgs.length) msgs[msgs.length - 1].remove();
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function updateDashboard() {
  const result = await api('status');
  const s = result.status || {};
  document.getElementById('dashRouter').textContent = s.router || 'Not discovered';
  document.getElementById('dashNodes').textContent = s.nodes || '0';
  document.getElementById('dashBackend').textContent = s.backend || '-';
  document.getElementById('dashModel').textContent = s.model || '-';
  document.getElementById('dashAIStatus').textContent = s.ai_available ? 'Available' : 'Unavailable';
  document.getElementById('dashAIStatus').className = 'badge ' + (s.ai_available ? 'success' : 'error');
  document.getElementById('dashTaskStatus').textContent = (s.task_status || 'idle').toUpperCase();
  document.getElementById('dashCompleted').textContent = s.tasks_completed || '0';
  document.getElementById('dashNodeName').textContent = s.node_name || '-';
  document.getElementById('dashNodeId').textContent = s.node_id || '-';

  const logPanel = document.getElementById('logPanel');
  if (result.logs && result.logs.length) {
    logPanel.textContent = result.logs.join('\\n');
    logPanel.scrollTop = logPanel.scrollHeight;
  }
}

let pollInterval;
function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(updateDashboard, 2000);
}

// Initialize
showStep(1);
fetch('/api?action=init').then(r => r.json()).then(d => {
  if (d.config) {
    document.getElementById('nodeName').value = d.config.node_name || '';
  }
});
</script>
</body>
</html>
"""


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path.startswith("/api?"):
            self._handle_api_get()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api":
            self._handle_api_post()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_api_get(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        action = params.get("action", [""])[0]

        if action == "init":
            self._json_response({"config": _app_state["config"]})
        else:
            self._json_response({"error": "unknown action"})

    def _handle_api_post(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json_response({"error": "invalid json"}, 400)
            return

        action = data.get("action", "")
        result = self._process_action(action, data)
        self._json_response(result)

    def _process_action(self, action: str, data: dict) -> dict:
        if action == "auto_scan":
            return self._do_auto_scan()
        elif action == "test_ai":
            return self._do_test_ai(data)
        elif action == "start_node":
            return self._do_start_node(data)
        elif action == "stop_node":
            return self._do_stop_node()
        elif action == "chat":
            return self._do_chat(data)
        elif action == "status":
            return self._do_status()
        return {"error": "unknown action"}

    def _do_auto_scan(self) -> dict:
        results = []
        found = None
        found_port = None
        found_model = None
        for name, port in BACKEND_PORTS.items():
            try:
                if name == "OpenAI":
                    sock = socket.create_connection(("api.openai.com", 443), timeout=2)
                    sock.close()
                    results.append({"name": name, "port": port, "ok": True, "info": "Port reachable"})
                else:
                    backend = BACKEND_ENUM_MAP[name]
                    adapter = ModelAdapter(backend, "http://localhost", port)
                    future = _runner.run(adapter.health_check())
                    ok = future.result(timeout=5)
                    if ok:
                        future2 = _runner.run(adapter.list_models())
                        models = future2.result(timeout=5)
                        info = f"{len(models)} models" if models else "healthy"
                        results.append({"name": name, "port": port, "ok": True, "info": info})
                        if not found:
                            found = name
                            found_port = port
                            found_model = models[0] if models else None
                    else:
                        results.append({"name": name, "port": port, "ok": False, "info": "No response"})
            except Exception as e:
                results.append({"name": name, "port": port, "ok": False, "info": str(e)})
        return {"results": results, "found": found, "port": found_port, "model": found_model}

    def _do_test_ai(self, data: dict) -> dict:
        try:
            name = data.get("backend", "Ollama")
            port = int(data.get("port", 11434))
            url = data.get("url", "http://localhost")
            model = data.get("model", "")
            backend = BACKEND_ENUM_MAP[name]
            adapter = ModelAdapter(backend, url, port)
            future = _runner.run(adapter.health_check())
            ok = future.result(timeout=10)
            if ok:
                future2 = _runner.run(adapter.list_models())
                models = future2.result(timeout=10)
                first_model = models[0] if models else ""
                _app_state["ai_adapter"] = adapter
                _app_state["config"].update({"backend": name, "url": url, "port": port, "model": model or first_model})
                return {"ok": True, "models": len(models), "model": first_model}
            return {"ok": False}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_start_node(self, data: dict) -> dict:
        try:
            node_name = data.get("node_name") or _app_state["config"]["node_name"]

            hermes = HermesComputeNode(
                node_name=node_name,
                capabilities=["inference", "embedding", "analysis", "tool_calling"]
            )

            _app_state["hermes_node"] = hermes
            _app_state["network_client"] = hermes.network_client
            _app_state["config"].update({
                "node_name": node_name
            })
            _app_state["status"]["node_running"] = True
            _log("Hermes Node starting...")

            def run_node():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(hermes.start())
                except Exception as e:
                    _log(f"Node error: {e}")

            t = threading.Thread(target=run_node, daemon=True)
            t.start()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_stop_node(self) -> dict:
        hermes = _app_state.get("hermes_node")
        if hermes:
            _runner.run(hermes.stop())
        _app_state["hermes_node"] = None
        _app_state["network_client"] = None
        _app_state["status"]["node_running"] = False
        _log("Node stopped")
        return {"ok": True}

    def _do_chat(self, data: dict) -> dict:
        text = data.get("message", "")
        hermes = _app_state.get("hermes_node")
        if hermes and hermes.agent_initialized:
            try:
                _app_state["chat_history"].append({"role": "user", "content": text})
                future = _runner.run(self._run_hermes_chat(hermes, text))
                response = future.result(timeout=60)
                _app_state["chat_history"].append({"role": "assistant", "content": response})
                return {"response": response}
            except Exception as e:
                return {"response": f"[Error: {e}]"}
        else:
            return {"response": "Hermes Agent not initialized. Please start the node first."}

    async def _run_hermes_chat(self, hermes, text: str) -> str:
        try:
            result = await hermes._run_inference(text)
            return result.get("response", "No response")
        except Exception as e:
            return f"[Error: {e}]"

    def _do_status(self) -> dict:
        hermes = _app_state.get("hermes_node")
        net = _app_state.get("network_client")
        cfg = _app_state["config"]
        _ = _app_state["status"]

        router_info = "Not discovered"
        nodes_count = 0
        if net:
            info = net.get_info()
            if info.get("connected"):
                router_info = f"{info.get('router_host')}:{info.get('router_port')}"

        ai_ok = False
        task_status = "idle"
        tasks_completed = 0
        node_id = ""
        node_name = cfg.get("node_name", "-")

        if hermes:
            try:
                s = hermes.get_status()
                ai_ok = s.get("hermes_available", False)
                task_status = s.get("task_status", "idle")
                tasks_completed = s.get("tasks_completed", 0)
                node_id = s.get("node_id", "")
                node_name = s.get("node_name", node_name)
            except Exception:
                pass

        return {
            "status": {
                "router": router_info,
                "nodes": nodes_count,
                "backend": "Hermes Agent",
                "model": "-",
                "ai_available": ai_ok,
                "task_status": task_status,
                "tasks_completed": tasks_completed,
                "node_id": node_id,
                "node_name": node_name,
            },
            "logs": _app_state["logs"][-50:],
        }

    def _json_response(self, data: dict, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def main():
    port = 8080
    server = HTTPServer(("0.0.0.0", port), RequestHandler)
    print(f"=" * 50)
    print(f"  NetConnect Node Web UI")
    print(f"=" * 50)
    print(f"  Open your browser and go to:")
    print(f"  http://localhost:{port}")
    print(f"=" * 50)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
