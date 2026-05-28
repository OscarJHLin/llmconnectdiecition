#!/usr/bin/env python3
"""
NetConnect Central Node Web UI
A browser-based dashboard for the central compute/network node.
Runs a local web server that can be accessed at http://localhost:8081
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
from typing import Dict, List, Optional, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from central.ai.model_adapter import ModelAdapter, ModelBackend
from central.compute.central_compute import CentralComputeNode, TaskType
from central.network.central_node import CentralNetworkNode

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

TASK_TYPE_MAP = {
    "inference": TaskType.INFERENCE,
    "embedding": TaskType.EMBEDDING,
    "analysis": TaskType.ANALYSIS,
    "aggregation": TaskType.AGGREGATION,
}

# Global state
_app_state = {
    "ai_adapter": None,
    "compute_node": None,
    "network_node": None,
    "config": {
        "backend": "Ollama",
        "url": "http://localhost",
        "port": 11434,
        "model": "",
        "node_name": "central-node",
        "host": "0.0.0.0",
        "port_network": 8888,
        "multicast_group": "224.0.0.1",
        "multicast_port": 5000,
        "feishu": {
            "enabled": False,
            "app_id": "",
            "app_secret": "",
            "connection_mode": "websocket",
            "webhook_host": "127.0.0.1",
            "webhook_port": 8765,
            "verification_token": "",
            "encrypt_key": "",
        },
        "weixin": {
            "enabled": False,
            "account_id": "",
            "token": "",
            "base_url": "https://ilinkai.weixin.qq.com",
        },
    },
    "status": {
        "ai_connected": False,
        "network_connected": False,
        "node_running": False,
        "tasks_pending": 0,
        "tasks_total": 0,
        "available_nodes": 0,
    },
    "logs": [],
    "chat_history": [],
    "tasks": [],
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
<title>NetConnect Central Dashboard</title>
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
.container { max-width: 1200px; margin: 0 auto; padding: 20px; }
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
.card {
  background: var(--surface);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 20px;
  border: 1px solid var(--border);
}
.card h2 { margin-top: 0; font-size: 1.2rem; color: var(--accent); }
.form-row { display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 15px; align-items: center; }
.form-row label { min-width: 140px; font-weight: 500; }
input, select, textarea {
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 14px;
  flex: 1;
  min-width: 200px;
  font-family: inherit;
}
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }
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
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; }
@media (max-width: 768px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
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
.tabs { display: flex; gap: 5px; margin-bottom: 15px; flex-wrap: wrap; }
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
.hidden { display: none; }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th, td {
  text-align: left;
  padding: 10px;
  border-bottom: 1px solid var(--border);
}
th { color: var(--accent); }
.topology-canvas {
  background: var(--bg);
  border-radius: 8px;
  width: 100%;
  height: 400px;
}
.small { font-size: 12px; color: var(--border); }
.switch {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
}
.switch input { opacity: 0; width: 0; height: 0; }
.slider {
  position: absolute;
  cursor: pointer;
  top: 0; left: 0; right: 0; bottom: 0;
  background-color: var(--border);
  transition: .4s;
  border-radius: 24px;
}
.slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: .4s;
  border-radius: 50%;
}
input:checked + .slider { background-color: var(--accent); }
input:checked + .slider:before { transform: translateX(20px); }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>NetConnect Central Dashboard</h1>
    <span class="badge info" id="headerStatus">Stopped</span>
  </header>

  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('chat')">Chat</button>
    <button class="tab-btn" onclick="switchTab('nodes')">Nodes</button>
    <button class="tab-btn" onclick="switchTab('topology')">Topology</button>
    <button class="tab-btn" onclick="switchTab('tasks')">Tasks</button>
    <button class="tab-btn" onclick="switchTab('settings')">Settings</button>
    <button class="tab-btn" onclick="switchTab('gateways')">Messaging Gateways</button>
    <button class="tab-btn" onclick="switchTab('logs')">Logs</button>
  </div>

  <!-- Chat Panel -->
  <div id="tab-chat" class="tab-content active">
    <div class="card">
      <h2>Central AI Chat</h2>
      <div class="chat-panel" id="chatPanel"></div>
      <div class="chat-input-row">
        <input type="text" id="chatInput" placeholder="Type a message..." onkeypress="if(event.key==='Enter')sendChat()">
        <button onclick="sendChat()">Send</button>
      </div>
    </div>
  </div>

  <!-- Nodes Panel -->
  <div id="tab-nodes" class="tab-content">
    <div class="card">
      <h2>Connected Nodes</h2>
      <div id="nodesTableWrap">
        <table>
          <thead>
            <tr><th>Name</th><th>ID</th><th>Type</th><th>Status</th><th>Capabilities</th><th>IP</th></tr>
          </thead>
          <tbody id="nodesTableBody"><tr><td colspan="6" class="small">No nodes connected</td></tr></tbody>
        </table>
      </div>
      <div style="margin-top:10px;">
        <button onclick="refreshNodes()">Refresh</button>
      </div>
    </div>
  </div>

  <!-- Topology Panel -->
  <div id="tab-topology" class="tab-content">
    <div class="card">
      <h2>Network Topology</h2>
      <canvas id="topologyCanvas" class="topology-canvas"></canvas>
    </div>
  </div>

  <!-- Tasks Panel -->
  <div id="tab-tasks" class="tab-content">
    <div class="card">
      <h2>Submit Task</h2>
      <div class="form-row">
        <label>Task Type:</label>
        <select id="taskType">
          <option value="inference">Inference</option>
          <option value="embedding">Embedding</option>
          <option value="analysis">Analysis</option>
          <option value="aggregation">Aggregation</option>
        </select>
      </div>
      <div class="form-row">
        <label>Description:</label>
        <input type="text" id="taskDesc" placeholder="Task description">
      </div>
      <div class="form-row">
        <label>Payload (JSON):</label>
        <textarea id="taskPayload" rows="3" placeholder='{"key":"value"}'></textarea>
      </div>
      <button onclick="submitTask()">Submit Task</button>
      <div id="taskSubmitResult" style="margin-top:10px;"></div>
    </div>
    <div class="card">
      <h2>Task Queue</h2>
      <table>
        <thead>
          <tr><th>ID</th><th>Type</th><th>Description</th><th>Status</th><th>Assigned</th></tr>
        </thead>
        <tbody id="tasksTableBody"><tr><td colspan="5" class="small">No tasks</td></tr></tbody>
      </table>
      <button onclick="refreshTasks()" style="margin-top:10px;">Refresh</button>
    </div>
  </div>

  <!-- Settings Panel -->
  <div id="tab-settings" class="tab-content">
    <div class="card">
      <h2>AI Backend</h2>
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
      <div id="scanResult" class="small hidden"></div>
      <button type="button" onclick="testAI()">Test AI Connection</button>
    </div>
    <div class="card">
      <h2>Network Configuration</h2>
      <div class="form-row">
        <label>Node Name:</label>
        <input type="text" id="nodeName" value="central-node">
      </div>
      <div class="form-row">
        <label>Host:</label>
        <input type="text" id="netHost" value="0.0.0.0">
      </div>
      <div class="form-row">
        <label>Port:</label>
        <input type="number" id="netPort" value="8888">
      </div>
      <div class="form-row">
        <label>Multicast Group:</label>
        <input type="text" id="multicastGroup" value="224.0.0.1">
      </div>
      <div class="form-row">
        <label>Multicast Port:</label>
        <input type="number" id="multicastPort" value="5000">
      </div>
    </div>
    <div class="card">
      <h2>Node Control</h2>
      <div class="form-row">
        <button id="startBtn" type="button" onclick="startNode()">Start Central Node</button>
        <button id="stopBtn" type="button" class="secondary" onclick="stopNode()" disabled>Stop Node</button>
        <span id="nodeStatusBadge" class="badge error">Stopped</span>
      </div>
    </div>
  </div>

  <!-- Gateways Panel -->
  <div id="tab-gateways" class="tab-content">
    <div class="card">
      <h2>Feishu (飞书)</h2>
      <div class="form-row">
        <label>Enabled:</label>
        <label class="switch">
          <input type="checkbox" id="feishuEnabled">
          <span class="slider"></span>
        </label>
      </div>
      <div class="form-row">
        <label>App ID:</label>
        <input type="text" id="feishuAppId" placeholder="cli_xxxxxxxx">
      </div>
      <div class="form-row">
        <label>App Secret:</label>
        <input type="password" id="feishuAppSecret" placeholder="secret">
      </div>
      <div class="form-row">
        <label>Connection Mode:</label>
        <select id="feishuMode">
          <option value="websocket">WebSocket</option>
          <option value="webhook">Webhook</option>
        </select>
      </div>
      <div class="form-row">
        <label>Webhook Host:</label>
        <input type="text" id="feishuWebhookHost" value="127.0.0.1">
      </div>
      <div class="form-row">
        <label>Webhook Port:</label>
        <input type="number" id="feishuWebhookPort" value="8765">
      </div>
      <div class="form-row">
        <label>Verification Token:</label>
        <input type="text" id="feishuVerificationToken" placeholder="Optional">
      </div>
      <div class="form-row">
        <label>Encrypt Key:</label>
        <input type="text" id="feishuEncryptKey" placeholder="Optional">
      </div>
      <button onclick="saveFeishuConfig()">Save Feishu Config</button>
      <span id="feishuSaveStatus" class="badge info hidden"></span>
    </div>

    <div class="card">
      <h2>Weixin (微信)</h2>
      <div class="form-row">
        <label>Enabled:</label>
        <label class="switch">
          <input type="checkbox" id="weixinEnabled">
          <span class="slider"></span>
        </label>
      </div>
      <div class="form-row">
        <label>Account ID:</label>
        <input type="text" id="weixinAccountId" placeholder="iLink bot id">
      </div>
      <div class="form-row">
        <label>Bot Token:</label>
        <input type="password" id="weixinToken" placeholder="bot token">
      </div>
      <div class="form-row">
        <label>Base URL:</label>
        <input type="text" id="weixinBaseUrl" value="https://ilinkai.weixin.qq.com">
      </div>
      <button onclick="saveWeixinConfig()">Save Weixin Config</button>
      <span id="weixinSaveStatus" class="badge info hidden"></span>
    </div>
  </div>

  <!-- Logs Panel -->
  <div id="tab-logs" class="tab-content">
    <div class="card">
      <h2>System Logs</h2>
      <div class="log-panel" id="logPanel">Waiting for logs...</div>
    </div>
  </div>
</div>

<script>
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'topology') drawTopology();
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
    host: document.getElementById('netHost').value,
    network_port: parseInt(document.getElementById('netPort').value),
    multicast_group: document.getElementById('multicastGroup').value,
    multicast_port: parseInt(document.getElementById('multicastPort').value),
  });
  if (result.ok) {
    setNodeStatus('Running', 'success');
    document.getElementById('stopBtn').disabled = false;
    document.getElementById('headerStatus').textContent = 'Running';
    document.getElementById('headerStatus').className = 'badge success';
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
  document.getElementById('headerStatus').textContent = 'Stopped';
  document.getElementById('headerStatus').className = 'badge error';
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

async function refreshNodes() {
  const result = await api('list_nodes');
  const tbody = document.getElementById('nodesTableBody');
  if (!result.nodes || result.nodes.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="small">No nodes connected</td></tr>';
    return;
  }
  tbody.innerHTML = result.nodes.map(n => {
    const statusClass = n.status === 'online' ? 'success' : (n.status === 'busy' ? 'warning' : 'error');
    return '<tr>' +
      '<td>' + escapeHtml(n.node_name) + '</td>' +
      '<td class="small">' + escapeHtml(n.node_id) + '</td>' +
      '<td>' + escapeHtml(n.node_type) + '</td>' +
      '<td><span class="badge ' + statusClass + '">' + escapeHtml(n.status) + '</span></td>' +
      '<td class="small">' + escapeHtml((n.capabilities || []).join(', ')) + '</td>' +
      '<td class="small">' + escapeHtml(n.ip_address) + '</td>' +
      '</tr>';
  }).join('');
}

async function submitTask() {
  const type = document.getElementById('taskType').value;
  const desc = document.getElementById('taskDesc').value;
  const payloadRaw = document.getElementById('taskPayload').value.trim();
  let payload = {};
  if (payloadRaw) {
    try { payload = JSON.parse(payloadRaw); } catch (e) {
      document.getElementById('taskSubmitResult').innerHTML = '<span class="badge error">Invalid JSON payload</span>';
      return;
    }
  }
  const result = await api('submit_task', {task_type: type, description: desc, payload});
  const el = document.getElementById('taskSubmitResult');
  if (result.ok) {
    el.innerHTML = '<span class="badge success">Task submitted: ' + escapeHtml(result.task_id) + '</span>';
    document.getElementById('taskDesc').value = '';
    document.getElementById('taskPayload').value = '';
    refreshTasks();
  } else {
    el.innerHTML = '<span class="badge error">Error: ' + escapeHtml(result.error || 'unknown') + '</span>';
  }
}

async function refreshTasks() {
  const result = await api('list_tasks');
  const tbody = document.getElementById('tasksTableBody');
  const tasks = result.tasks || [];
  if (tasks.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="small">No tasks</td></tr>';
    return;
  }
  tbody.innerHTML = tasks.map(t => {
    const statusClass = t.status === 'completed' ? 'success' : (t.status === 'failed' ? 'error' : (t.status === 'in_progress' ? 'warning' : 'info'));
    return '<tr>' +
      '<td class="small">' + escapeHtml(t.task_id) + '</td>' +
      '<td>' + escapeHtml(t.task_type) + '</td>' +
      '<td>' + escapeHtml(t.description) + '</td>' +
      '<td><span class="badge ' + statusClass + '">' + escapeHtml(t.status) + '</span></td>' +
      '<td class="small">' + escapeHtml(t.assigned_node || '-') + '</td>' +
      '</tr>';
  }).join('');
}

function drawTopology() {
  const canvas = document.getElementById('topologyCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  const w = rect.width;
  const h = rect.height;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  ctx.fillRect(0, 0, w, h);

  api('list_nodes').then(result => {
    const nodes = result.nodes || [];
    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(w, h) * 0.35;

    // Draw central node
    ctx.beginPath();
    ctx.arc(cx, cy, 28, 0, Math.PI * 2);
    ctx.fillStyle = '#89b4fa';
    ctx.fill();
    ctx.fillStyle = '#1e1e2e';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Central', cx, cy);

    const count = nodes.length || 1;
    nodes.forEach((n, i) => {
      const angle = (Math.PI * 2 * i) / count - Math.PI / 2;
      const nx = cx + Math.cos(angle) * radius;
      const ny = cy + Math.sin(angle) * radius;

      // Line
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(nx, ny);
      ctx.strokeStyle = '#585b70';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Node circle
      ctx.beginPath();
      ctx.arc(nx, ny, 20, 0, Math.PI * 2);
      ctx.fillStyle = n.status === 'online' ? '#a6e3a1' : (n.status === 'busy' ? '#f9e2af' : '#f38ba8');
      ctx.fill();

      // Label
      ctx.fillStyle = '#cdd6f4';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(n.node_name || 'Node', nx, ny + 34);
    });
  });
}

async function saveFeishuConfig() {
  const data = {
    enabled: document.getElementById('feishuEnabled').checked,
    app_id: document.getElementById('feishuAppId').value,
    app_secret: document.getElementById('feishuAppSecret').value,
    connection_mode: document.getElementById('feishuMode').value,
    webhook_host: document.getElementById('feishuWebhookHost').value,
    webhook_port: parseInt(document.getElementById('feishuWebhookPort').value),
    verification_token: document.getElementById('feishuVerificationToken').value,
    encrypt_key: document.getElementById('feishuEncryptKey').value,
  };
  const result = await api('save_feishu', data);
  const el = document.getElementById('feishuSaveStatus');
  el.classList.remove('hidden');
  el.textContent = result.ok ? 'Saved' : ('Error: ' + (result.error || ''));
  el.className = 'badge ' + (result.ok ? 'success' : 'error');
}

async function saveWeixinConfig() {
  const data = {
    enabled: document.getElementById('weixinEnabled').checked,
    account_id: document.getElementById('weixinAccountId').value,
    token: document.getElementById('weixinToken').value,
    base_url: document.getElementById('weixinBaseUrl').value,
  };
  const result = await api('save_weixin', data);
  const el = document.getElementById('weixinSaveStatus');
  el.classList.remove('hidden');
  el.textContent = result.ok ? 'Saved' : ('Error: ' + (result.error || ''));
  el.className = 'badge ' + (result.ok ? 'success' : 'error');
}

async function updateDashboard() {
  const result = await api('status');
  const s = result.status || {};
  document.getElementById('headerStatus').textContent = s.node_running ? 'Running' : 'Stopped';
  document.getElementById('headerStatus').className = 'badge ' + (s.node_running ? 'success' : 'error');

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
fetch('/api?action=init').then(r => r.json()).then(d => {
  if (d.config) {
    const c = d.config;
    if (c.backend) document.getElementById('backendSelect').value = c.backend;
    if (c.url) document.getElementById('backendUrl').value = c.url;
    if (c.port) document.getElementById('backendPort').value = c.port;
    if (c.model) document.getElementById('backendModel').value = c.model;
    if (c.node_name) document.getElementById('nodeName').value = c.node_name;
    if (c.host) document.getElementById('netHost').value = c.host;
    if (c.port_network) document.getElementById('netPort').value = c.port_network;
    if (c.multicast_group) document.getElementById('multicastGroup').value = c.multicast_group;
    if (c.multicast_port) document.getElementById('multicastPort').value = c.multicast_port;
    if (c.feishu) {
      document.getElementById('feishuEnabled').checked = !!c.feishu.enabled;
      if (c.feishu.app_id) document.getElementById('feishuAppId').value = c.feishu.app_id;
      if (c.feishu.app_secret) document.getElementById('feishuAppSecret').value = c.feishu.app_secret;
      if (c.feishu.connection_mode) document.getElementById('feishuMode').value = c.feishu.connection_mode;
      if (c.feishu.webhook_host) document.getElementById('feishuWebhookHost').value = c.feishu.webhook_host;
      if (c.feishu.webhook_port) document.getElementById('feishuWebhookPort').value = c.feishu.webhook_port;
      if (c.feishu.verification_token) document.getElementById('feishuVerificationToken').value = c.feishu.verification_token;
      if (c.feishu.encrypt_key) document.getElementById('feishuEncryptKey').value = c.feishu.encrypt_key;
    }
    if (c.weixin) {
      document.getElementById('weixinEnabled').checked = !!c.weixin.enabled;
      if (c.weixin.account_id) document.getElementById('weixinAccountId').value = c.weixin.account_id;
      if (c.weixin.token) document.getElementById('weixinToken').value = c.weixin.token;
      if (c.weixin.base_url) document.getElementById('weixinBaseUrl').value = c.weixin.base_url;
    }
  }
  if (d.status && d.status.node_running) {
    setNodeStatus('Running', 'success');
    document.getElementById('startBtn').disabled = true;
    document.getElementById('stopBtn').disabled = false;
    document.getElementById('headerStatus').textContent = 'Running';
    document.getElementById('headerStatus').className = 'badge success';
    startPolling();
  }
});
</script>
</body>
</html>
"""


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
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
            self._json_response({"config": _app_state["config"], "status": _app_state["status"]})
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
        elif action == "list_nodes":
            return self._do_list_nodes()
        elif action == "submit_task":
            return self._do_submit_task(data)
        elif action == "list_tasks":
            return self._do_list_tasks()
        elif action == "save_feishu":
            return self._do_save_feishu(data)
        elif action == "save_weixin":
            return self._do_save_weixin(data)
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
            name = data.get("backend", "Ollama")
            port = int(data.get("port", 11434))
            url = data.get("url", "http://localhost")
            model = data.get("model", "")
            node_name = data.get("node_name") or _app_state["config"]["node_name"]
            host = data.get("host", "0.0.0.0")
            network_port = int(data.get("network_port", 8888))
            multicast_group = data.get("multicast_group", "224.0.0.1")
            multicast_port = int(data.get("multicast_port", 5000))
            backend = BACKEND_ENUM_MAP[name]

            compute = CentralComputeNode(
                node_name=node_name,
                ai_backend=backend,
                ai_port=port
            )
            compute.ai_adapter = ModelAdapter(backend, url, port)
            if model:
                compute.ai_adapter.set_default_model(model)
            else:
                future_models = _runner.run(compute.ai_adapter.list_models())
                models = future_models.result(timeout=10)
                if models:
                    compute.ai_adapter.set_default_model(models[0])
                    model = models[0]

            network = CentralNetworkNode(
                host=host,
                port=network_port,
                multicast_group=multicast_group,
                multicast_port=multicast_port
            )

            _app_state["compute_node"] = compute
            _app_state["network_node"] = network
            _app_state["config"].update({
                "backend": name, "url": url, "port": port, "model": model or compute.ai_adapter._default_model or "",
                "node_name": node_name, "host": host, "port_network": network_port,
                "multicast_group": multicast_group, "multicast_port": multicast_port,
            })
            _app_state["status"]["node_running"] = True
            _log("Central node starting...")

            def run_compute():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(compute.start())
                except Exception as e:
                    _log(f"Compute node error: {e}")

            def run_network():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(network.start())
                except Exception as e:
                    _log(f"Network node error: {e}")

            tc = threading.Thread(target=run_compute, daemon=True)
            tn = threading.Thread(target=run_network, daemon=True)
            tc.start()
            tn.start()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_stop_node(self) -> dict:
        compute = _app_state.get("compute_node")
        network = _app_state.get("network_node")
        if compute:
            _runner.run(compute.stop())
        if network:
            _runner.run(network.stop())
        _app_state["compute_node"] = None
        _app_state["network_node"] = None
        _app_state["status"]["node_running"] = False
        _log("Central node stopped")
        return {"ok": True}

    def _do_chat(self, data: dict) -> dict:
        text = data.get("message", "")
        adapter = None
        compute = _app_state.get("compute_node")
        if compute:
            adapter = compute.ai_adapter
        else:
            adapter = _app_state.get("ai_adapter")
        if not adapter:
            return {"response": "No AI backend configured."}
        if not adapter._default_model:
            try:
                future = _runner.run(adapter.list_models())
                models = future.result(timeout=10)
                if models:
                    adapter.set_default_model(models[0])
                else:
                    return {"response": "No models available."}
            except Exception as e:
                return {"response": f"[Error loading models: {e}]"}
        try:
            _app_state["chat_history"].append({"role": "user", "content": text})
            future = _runner.run(adapter.generate(text))
            result = future.result(timeout=60)
            response = result.get("response", "")
            if not response and "error" in result:
                response = f"[Error: {result['error']}]"
            _app_state["chat_history"].append({"role": "assistant", "content": response})
            return {"response": response}
        except Exception as e:
            return {"response": f"[Error: {e}]"}

    def _do_status(self) -> dict:
        compute = _app_state.get("compute_node")
        network = _app_state.get("network_node")
        cfg = _app_state["config"]
        status = _app_state["status"]

        ai_ok = False
        node_running = False
        tasks_pending = 0
        tasks_total = 0
        available_nodes = 0

        if compute:
            try:
                future = _runner.run(compute.get_status())
                s = future.result(timeout=5)
                ai_ok = s.get("ai_connected", False)
                node_running = s.get("connected", False)
                tasks_pending = s.get("tasks_pending", 0)
                tasks_total = s.get("tasks_total", 0)
                available_nodes = s.get("available_nodes", 0)
            except Exception:
                pass

        if network:
            try:
                available_nodes = len(network.connected_nodes)
            except Exception:
                pass

        return {
            "status": {
                "node_running": _app_state["status"]["node_running"],
                "ai_connected": ai_ok,
                "network_connected": node_running,
                "tasks_pending": tasks_pending,
                "tasks_total": tasks_total,
                "available_nodes": available_nodes,
                "backend": cfg.get("backend", "-"),
                "model": cfg.get("model", "-"),
                "node_name": cfg.get("node_name", "-"),
            },
            "logs": _app_state["logs"][-50:],
        }

    def _do_list_nodes(self) -> dict:
        network = _app_state.get("network_node")
        nodes = []
        if network:
            try:
                for nid, n in network.connected_nodes.items():
                    nodes.append({
                        "node_id": nid,
                        "node_name": n.node_name,
                        "node_type": n.node_type.value,
                        "status": n.status.value,
                        "capabilities": n.capabilities,
                        "ip_address": n.ip_address,
                    })
            except Exception as e:
                return {"error": str(e), "nodes": []}
        return {"nodes": nodes}

    def _do_submit_task(self, data: dict) -> dict:
        compute = _app_state.get("compute_node")
        if not compute:
            return {"ok": False, "error": "Central compute node is not running"}
        ttype = data.get("task_type", "inference")
        description = data.get("description", "")
        payload = data.get("payload", {})
        task_type_enum = TASK_TYPE_MAP.get(ttype, TaskType.INFERENCE)
        try:
            future = _runner.run(compute.submit_task(task_type_enum, description, payload))
            task_id = future.result(timeout=10)
            _app_state["tasks"].append({
                "task_id": task_id,
                "task_type": ttype,
                "description": description,
                "status": "pending",
                "assigned_node": None,
            })
            return {"ok": True, "task_id": task_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_list_tasks(self) -> dict:
        compute = _app_state.get("compute_node")
        tasks = []
        if compute:
            try:
                for tid, task in compute.tasks.items():
                    tasks.append({
                        "task_id": tid,
                        "task_type": task.task_type.value,
                        "description": task.description,
                        "status": task.status.value,
                        "assigned_node": task.assigned_node,
                    })
            except Exception:
                pass
        # Fallback to local cache if compute not ready
        if not tasks:
            tasks = _app_state.get("tasks", [])
        return {"tasks": tasks}

    def _do_save_feishu(self, data: dict) -> dict:
        try:
            _app_state["config"]["feishu"].update({
                "enabled": bool(data.get("enabled", False)),
                "app_id": str(data.get("app_id", "")),
                "app_secret": str(data.get("app_secret", "")),
                "connection_mode": str(data.get("connection_mode", "websocket")),
                "webhook_host": str(data.get("webhook_host", "127.0.0.1")),
                "webhook_port": int(data.get("webhook_port", 8765)),
                "verification_token": str(data.get("verification_token", "")),
                "encrypt_key": str(data.get("encrypt_key", "")),
            })
            _log("Feishu config saved")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_save_weixin(self, data: dict) -> dict:
        try:
            _app_state["config"]["weixin"].update({
                "enabled": bool(data.get("enabled", False)),
                "account_id": str(data.get("account_id", "")),
                "token": str(data.get("token", "")),
                "base_url": str(data.get("base_url", "https://ilinkai.weixin.qq.com")),
            })
            _log("Weixin config saved")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _json_response(self, data: dict, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def main():
    port = 8081
    server = HTTPServer(("0.0.0.0", port), RequestHandler)
    print(f"=" * 50)
    print(f"  NetConnect Central Web UI")
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
