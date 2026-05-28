#!/usr/bin/env python3
"""
NetConnect Windows Sub Node - Windows子节点
包含网络子节点和计算子节点功能，带Web UI
运行方式: python main.py
"""

import sys
import os
import socket
import json
import asyncio
import threading
import time
import uuid
import struct
from datetime import datetime
from typing import Optional, Dict, List, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

BACKEND_PORTS = {
    "Ollama": 11434,
    "vLLM": 8000,
    "LM Studio": 1234,
    "OpenAI": 443,
}

_app_state = {
    "sub_node": None,
    "network_client": None,
    "config": {
        "backend": "Ollama",
        "backend_url": "http://localhost",
        "backend_port": 11434,
        "model": "",
        "node_name": f"windows-node-{uuid.uuid4().hex[:6]}",
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
        self.loop = None
        self._thread = None
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

class ModelAdapter:
    def __init__(self, backend: str, base_url: str, port: int):
        self.backend = backend
        self.base_url = base_url
        self.port = port
        self._default_model = None

    def set_default_model(self, model: str):
        self._default_model = model

    async def health_check(self) -> bool:
        try:
            if self.backend == "OpenAI":
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex(("api.openai.com", 443))
                sock.close()
                return result == 0
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((self.base_url.replace("http://", ""), self.port))
                sock.close()
                return result == 0
        except:
            return False

    async def list_models(self) -> List[str]:
        try:
            import requests
            url = f"{self.base_url}:{self.port}/v1/models"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [m["id"] for m in data.get("data", [])]
        except:
            pass
        return []

    async def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> Dict[str, Any]:
        try:
            import requests
            url = f"{self.base_url}:{self.port}/v1/chat/completions"
            payload = {
                "model": self._default_model or "default",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }
            response = requests.post(url, json=payload, timeout=60)
            if response.status_code == 200:
                data = response.json()
                return {"response": data["choices"][0]["message"]["content"]}
            return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

class NetworkClient:
    def __init__(self, node_name: str, multicast_group: str = "224.0.0.1", multicast_port: int = 5000):
        self.node_name = node_name
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.router_host = None
        self.router_port = 8888
        self.connected = False
        self._reader = None
        self._writer = None
        self._message_handler = None

    def set_message_handler(self, handler):
        self._message_handler = handler

    async def _discover_router(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(3)
        try:
            message = json.dumps({"type": "DISCOVER", "node_name": self.node_name}).encode('utf-8')
            sock.sendto(message, (self.multicast_group, self.multicast_port))
            data, addr = sock.recvfrom(1024)
            response = json.loads(data.decode('utf-8'))
            if response.get("type") == "DISCOVER_RESPONSE":
                self.router_host = addr[0]
                self.router_port = response.get("port", 8888)
                _log(f"Discovered router at {self.router_host}:{self.router_port}")
                return True
        except:
            pass
        return False

    async def _send_message_with_length(self, writer, data):
        message = json.dumps(data).encode('utf-8')
        length = len(message)
        writer.write(struct.pack('!I', length))
        writer.write(message)
        await writer.drain()

    async def _read_message_with_length(self, reader):
        try:
            length_data = await reader.readexactly(4)
            length = struct.unpack('!I', length_data)[0]
            message_data = await reader.readexactly(length)
            return json.loads(message_data.decode('utf-8'))
        except:
            return None

    async def connect(self):
        if not self.router_host:
            if not await self._discover_router():
                _log("Failed to discover router")
                return False
        try:
            self._reader, self._writer = await asyncio.open_connection(self.router_host, self.router_port)
            await self._send_message_with_length(self._writer, {
                "type": "REGISTER",
                "node_name": self.node_name,
                "node_type": "COMPUTE",
                "capabilities": ["inference", "embedding", "analysis"]
            })
            response = await self._read_message_with_length(self._reader)
            if response and response.get("status") == "OK":
                self.connected = True
                _log(f"Connected to router: {self.router_host}:{self.router_port}")
                asyncio.create_task(self._listen_loop())
                asyncio.create_task(self._send_heartbeat())
                return True
        except Exception as e:
            _log(f"Connection failed: {e}")
        return False

    async def _listen_loop(self):
        while self.connected and self._reader:
            message = await self._read_message_with_length(self._reader)
            if message:
                _log(f"Received: {message.get('type', 'unknown')}")
                if self._message_handler:
                    handler = self._message_handler
                    if asyncio.iscoroutinefunction(handler):
                        await handler(message)
                    else:
                        handler(message)
            else:
                self.connected = False
                _log("Connection closed")
                break

    async def _send_heartbeat(self):
        while self.connected and self._writer:
            try:
                await self._send_message_with_length(self._writer, {"type": "HEARTBEAT"})
                await asyncio.sleep(5)
            except:
                self.connected = False
                break

    async def send_task_result(self, task_id: str, result: Dict):
        if self.connected and self._writer:
            await self._send_message_with_length(self._writer, {
                "type": "TASK_RESULT",
                "task_id": task_id,
                "result": result
            })

    def get_info(self):
        return {
            "connected": self.connected,
            "router_host": self.router_host,
            "router_port": self.router_port,
            "node_name": self.node_name
        }

class SubComputeNode:
    def __init__(self, node_name: str = None, capabilities: List[str] = None):
        self.node_id = str(uuid.uuid4())
        self.node_name = node_name or f"sub_node_{self.node_id[:8]}"
        self.capabilities = capabilities or ["inference", "embedding"]
        self.agent_initialized = False
        self.ai_adapter = None
        self.network_client = NetworkClient(self.node_name)
        self.network_client.set_message_handler(self._handle_network_message)
        self.task_history = []

    async def _handle_network_message(self, message):
        msg_type = message.get("type")
        if msg_type == "TASK_ASSIGN":
            await self._handle_task(message)

    async def _handle_task(self, message):
        task_id = message.get("task_id")
        task_type = message.get("task_type")
        payload = message.get("payload", {})
        _log(f"Received task: {task_id} - {task_type}")
        try:
            if task_type == "inference":
                prompt = payload.get("prompt", "")
                result = await self._run_inference(prompt)
            else:
                result = {"response": f"Task {task_type} completed"}
            self.task_history.append({"task_id": task_id, "type": task_type, "status": "completed"})
            await self.network_client.send_task_result(task_id, result)
        except Exception as e:
            _log(f"Task error: {e}")
            await self.network_client.send_task_result(task_id, {"error": str(e)})

    async def _run_inference(self, prompt: str) -> Dict:
        if self.ai_adapter:
            return await self.ai_adapter.generate(prompt)
        return {"response": "AI adapter not configured"}

    def get_status(self):
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "agent_initialized": self.agent_initialized,
            "task_status": "idle",
            "tasks_completed": len(self.task_history),
            "capabilities": self.capabilities,
            "network_connected": self.network_client.connected
        }

    async def start(self):
        _log("Starting sub compute node...")
        await self.network_client.connect()
        self.agent_initialized = True

    async def stop(self):
        self.agent_initialized = False

HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NetConnect Windows Sub Node</title>
<style>
:root { --bg: #0f1117; --fg: #e2e8f0; --accent: #3b82f6; --success: #22c55e; --warning: #f59e0b; --error: #ef4444; --surface: #1e293b; --border: #334155; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--fg); }
.container { max-width: 900px; margin: 0 auto; padding: 20px; }
.header { text-align: center; margin-bottom: 30px; }
.header h1 { color: var(--accent); margin: 0; }
.header p { color: #94a3b8; }
.step { background: var(--surface); border-radius: 12px; padding: 24px; margin-bottom: 20px; }
.step-title { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.step-number { width: 32px; height: 32px; border-radius: 50%; background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center; font-weight: bold; }
.step h2 { margin: 0; color: var(--fg); }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 8px; font-weight: 500; }
.form-group input, .form-group select { width: 100%; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--fg); font-size: 14px; }
.btn { padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-success { background: var(--success); color: #fff; }
.btn-danger { background: var(--error); color: #fff; }
.badge { padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; }
.badge.success { background: rgba(34,197,94,0.2); color: var(--success); }
.badge.error { background: rgba(239,68,68,0.2); color: var(--error); }
.status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
.status-card { background: var(--surface); padding: 16px; border-radius: 8px; text-align: center; }
.status-card .label { font-size: 12px; color: #94a3b8; }
.status-card .value { font-size: 18px; font-weight: bold; margin-top: 4px; }
.tab-container { display: flex; gap: 8px; margin-bottom: 16px; }
.tab { padding: 10px 20px; border: none; border-radius: 8px; background: var(--surface); color: var(--fg); cursor: pointer; }
.tab.active { background: var(--accent); color: #fff; }
.tab-content { display: none; }
.tab-content.active { display: block; }
.chat-container { background: var(--surface); border-radius: 8px; overflow: hidden; }
.chat-messages { height: 300px; overflow-y: auto; padding: 16px; }
.chat-message { margin-bottom: 12px; }
.chat-message.user .msg-content { background: var(--accent); color: #fff; }
.chat-message.assistant .msg-content { background: var(--border); }
.msg-content { padding: 10px 14px; border-radius: 16px; max-width: 80%; }
.chat-input { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--border); }
.chat-input input { flex: 1; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--fg); }
.chat-input button { padding: 10px 20px; background: var(--accent); color: #fff; border: none; border-radius: 8px; cursor: pointer; }
.log-panel { background: #0f1117; padding: 12px; border-radius: 8px; height: 200px; overflow-y: auto; font-family: "Consolas", monospace; font-size: 12px; white-space: pre-wrap; }
.scan-result { margin-top: 16px; padding: 12px; background: rgba(0,0,0,0.2); border-radius: 8px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>NetConnect Sub Node</h1>
    <p>Windows 子节点 - 网络+计算融合节点</p>
  </div>

  <div class="step">
    <div class="step-title">
      <div class="step-number">1</div>
      <h2>AI后端配置</h2>
    </div>
    <div class="form-group">
      <label>AI后端</label>
      <select id="backendSelect" onchange="updateBackendConfig()">
        <option value="Ollama">Ollama</option>
        <option value="vLLM">vLLM</option>
        <option value="LM Studio">LM Studio</option>
        <option value="OpenAI">OpenAI</option>
      </select>
    </div>
    <div class="form-group">
      <label>后端地址</label>
      <input type="text" id="backendUrl" value="http://localhost">
    </div>
    <div class="form-group">
      <label>后端端口</label>
      <input type="number" id="backendPort" value="11434">
    </div>
    <div class="form-group">
      <label>模型名称</label>
      <input type="text" id="modelName" placeholder="自动检测或手动输入">
    </div>
    <button class="btn btn-primary" onclick="autoScan()">自动扫描</button>
    <div id="scanResult" class="scan-result" style="display:none;"></div>
  </div>

  <div class="step">
    <div class="step-title">
      <div class="step-number">2</div>
      <h2>网络配置</h2>
    </div>
    <div class="form-group">
      <label>节点名称</label>
      <input type="text" id="nodeName" placeholder="输入节点名称">
    </div>
    <div class="form-group">
      <label>网络组播地址</label>
      <input type="text" id="multicastGroup" value="224.0.0.1">
    </div>
    <div class="form-group">
      <label>组播端口</label>
      <input type="number" id="multicastPort" value="5000">
    </div>
  </div>

  <div class="step">
    <div class="step-title">
      <div class="step-number">3</div>
      <h2>启动节点</h2>
    </div>
    <button class="btn btn-success" id="startBtn" onclick="startNode()">启动节点</button>
    <button class="btn btn-danger" id="stopBtn" onclick="stopNode()" disabled>停止节点</button>
    <span id="nodeStatus" class="badge error" style="margin-left: 12px;">已停止</span>
  </div>

  <div class="step">
    <div class="step-title">
      <div class="step-number">4</div>
      <h2>仪表盘</h2>
    </div>
    <div class="tab-container">
      <button class="tab active" onclick="showTab('dashboard')">状态</button>
      <button class="tab" onclick="showTab('chat')">聊天</button>
      <button class="tab" onclick="showTab('logs')">日志</button>
    </div>
    <div id="dashboard" class="tab-content active">
      <div class="status-grid">
        <div class="status-card" id="routerStatus">
          <div class="label">路由器</div>
          <div class="value">未连接</div>
        </div>
        <div class="status-card" id="aiStatus">
          <div class="label">AI后端</div>
          <div class="value">未连接</div>
        </div>
        <div class="status-card" id="nodeStatusCard">
          <div class="label">节点状态</div>
          <div class="value">已停止</div>
        </div>
        <div class="status-card" id="tasksStatus">
          <div class="label">完成任务</div>
          <div class="value">0</div>
        </div>
      </div>
    </div>
    <div id="chat" class="tab-content">
      <div class="chat-container">
        <div class="chat-messages" id="chatMessages"></div>
        <div class="chat-input">
          <input type="text" id="chatInput" placeholder="输入消息..." onkeydown="if(event.keyCode===13) sendMessage()">
          <button onclick="sendMessage()">发送</button>
        </div>
      </div>
    </div>
    <div id="logs" class="tab-content">
      <div class="log-panel" id="logPanel"></div>
    </div>
  </div>
</div>

<script>
let pollInterval;
const backendPorts = {"Ollama": 11434, "vLLM": 8000, "LM Studio": 1234, "OpenAI": 443};

function updateBackendConfig() {
  const backend = document.getElementById('backendSelect').value;
  document.getElementById('backendPort').value = backendPorts[backend];
}

function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById(name).classList.add('active');
}

async function api(action, data = {}) {
  const response = await fetch('/api', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, ...data })
  });
  return response.json();
}

async function autoScan() {
  const result = await api('auto_scan');
  const el = document.getElementById('scanResult');
  if (result.ok && result.model) {
    document.getElementById('modelName').value = result.model;
    el.innerHTML = `<span style="color: var(--success);">✓ 检测到模型: ${result.model} (${result.backend})</span>`;
  } else {
    el.innerHTML = `<span style="color: var(--error);">✗ 未检测到AI后端</span>`;
  }
  el.style.display = 'block';
}

async function startNode() {
  const data = {
    node_name: document.getElementById('nodeName').value,
    multicast_group: document.getElementById('multicastGroup').value,
    multicast_port: parseInt(document.getElementById('multicastPort').value),
    backend: document.getElementById('backendSelect').value,
    backend_url: document.getElementById('backendUrl').value,
    backend_port: parseInt(document.getElementById('backendPort').value),
    model: document.getElementById('modelName').value
  };
  const result = await api('start_node', data);
  if (result.ok) {
    document.getElementById('startBtn').disabled = true;
    document.getElementById('stopBtn').disabled = false;
    document.getElementById('nodeStatus').textContent = '运行中';
    document.getElementById('nodeStatus').className = 'badge success';
    startPolling();
  } else {
    alert('启动失败: ' + result.error);
  }
}

async function stopNode() {
  await api('stop_node');
  document.getElementById('startBtn').disabled = false;
  document.getElementById('stopBtn').disabled = true;
  document.getElementById('nodeStatus').textContent = '已停止';
  document.getElementById('nodeStatus').className = 'badge error';
  stopPolling();
}

async function sendMessage() {
  const text = document.getElementById('chatInput').value.trim();
  if (!text) return;
  const model = document.getElementById('modelName').value;
  if (!model) { alert('请先配置AI模型'); return; }
  document.getElementById('chatInput').value = '';
  addChatMessage('user', text);
  const result = await api('chat', { message: text, model: model });
  addChatMessage('assistant', result.response);
}

function addChatMessage(role, content) {
  const el = document.getElementById('chatMessages');
  el.innerHTML += `<div class="chat-message ${role}"><div class="msg-content">${content}</div></div>`;
  el.scrollTop = el.scrollHeight;
}

async function updateDashboard() {
  const result = await api('status');
  const s = result.status || {};
  
  const routerCard = document.getElementById('routerStatus');
  routerCard.className = 'status-card ' + (s.router && s.router !== 'Not discovered' ? 'success' : 'error');
  routerCard.querySelector('.value').textContent = s.router || '未连接';
  
  const aiCard = document.getElementById('aiStatus');
  aiCard.className = 'status-card ' + (s.ai_connected ? 'success' : 'error');
  aiCard.querySelector('.value').textContent = s.ai_connected ? '已连接' : '未连接';
  
  const nodeCard = document.getElementById('nodeStatusCard');
  nodeCard.className = 'status-card ' + (s.node_running ? 'success' : 'error');
  nodeCard.querySelector('.value').textContent = s.node_running ? '运行中' : '已停止';
  
  document.getElementById('tasksStatus').querySelector('.value').textContent = s.tasks_completed || '0';
  
  const logPanel = document.getElementById('logPanel');
  if (result.logs && result.logs.length) {
    logPanel.textContent = result.logs.join('\\n');
    logPanel.scrollTop = logPanel.scrollHeight;
  }
}

function startPolling() {
  stopPolling();
  pollInterval = setInterval(updateDashboard, 2000);
  updateDashboard();
}

function stopPolling() {
  if (pollInterval) clearInterval(pollInterval);
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('nodeName').value = 'windows-node-' + Math.random().toString(36).substr(2, 6);
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
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            try:
                data = json.loads(body)
            except:
                self._json_response({"error": "invalid json"}, 400)
                return
            action = data.get("action", "")
            result = self._process_action(action, data)
            self._json_response(result)
        else:
            self.send_response(404)
            self.end_headers()

    def _process_action(self, action, data):
        if action == "start_node":
            return self._do_start_node(data)
        elif action == "stop_node":
            return self._do_stop_node()
        elif action == "chat":
            return self._do_chat(data)
        elif action == "status":
            return self._do_status()
        elif action == "auto_scan":
            return self._do_auto_scan()
        return {"error": "unknown action"}

    def _do_start_node(self, data):
        try:
            node_name = data.get("node_name") or _app_state["config"]["node_name"]
            multicast_group = data.get("multicast_group", "224.0.0.1")
            multicast_port = int(data.get("multicast_port", 5000))
            backend = data.get("backend", "Ollama")
            backend_url = data.get("backend_url", "http://localhost")
            backend_port = int(data.get("backend_port", 11434))
            model = data.get("model", "")

            sub = SubComputeNode(node_name=node_name, capabilities=["inference", "embedding", "analysis"])
            sub.network_client.multicast_group = multicast_group
            sub.network_client.multicast_port = multicast_port

            adapter = ModelAdapter(backend, backend_url, backend_port)
            if model:
                adapter.set_default_model(model)
            sub.ai_adapter = adapter

            _app_state["sub_node"] = sub
            _app_state["network_client"] = sub.network_client
            _app_state["config"].update({
                "node_name": node_name,
                "backend": backend,
                "backend_url": backend_url,
                "backend_port": backend_port,
                "model": model
            })
            _app_state["status"]["node_running"] = True
            _log("Sub node starting...")

            def run_node():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(sub.start())
                except Exception as e:
                    _log(f"Node error: {e}")

            t = threading.Thread(target=run_node, daemon=True)
            t.start()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_stop_node(self):
        sub = _app_state.get("sub_node")
        if sub:
            _runner.run(sub.stop())
        _app_state["sub_node"] = None
        _app_state["network_client"] = None
        _app_state["status"]["node_running"] = False
        _app_state["status"]["ai_connected"] = False
        _log("Node stopped")
        return {"ok": True}

    def _do_chat(self, data):
        text = data.get("message", "")
        model = data.get("model", "")
        sub = _app_state.get("sub_node")
        if sub and sub.agent_initialized and sub.ai_adapter:
            try:
                if model:
                    sub.ai_adapter.set_default_model(model)
                _app_state["chat_history"].append({"role": "user", "content": text})
                future = _runner.run(sub._run_inference(text))
                response = future.result(timeout=60)
                _app_state["chat_history"].append({"role": "assistant", "content": response.get("response", "")})
                return {"response": response.get("response", "No response")}
            except Exception as e:
                return {"response": f"[Error: {e}]"}
        else:
            return {"response": "Node not initialized or AI not configured."}

    def _do_status(self):
        sub = _app_state.get("sub_node")
        net = _app_state.get("network_client")
        cfg = _app_state["config"]

        router_info = "Not discovered"
        if net:
            info = net.get_info()
            if info.get("connected"):
                router_info = f"{info.get('router_host')}:{info.get('router_port')}"

        ai_ok = False
        tasks_completed = 0
        node_id = ""

        if sub:
            s = sub.get_status()
            ai_ok = s.get("agent_initialized", False)
            tasks_completed = s.get("tasks_completed", 0)
            node_id = s.get("node_id", "")

        return {
            "status": {
                "router": router_info,
                "backend": cfg.get("backend", "-"),
                "ai_connected": ai_ok,
                "tasks_completed": tasks_completed,
                "node_id": node_id,
                "node_name": cfg.get("node_name", "-"),
                "node_running": _app_state["status"]["node_running"],
            },
            "logs": _app_state["logs"][-50:],
        }

    def _do_auto_scan(self):
        backends = [
            ("Ollama", "http://localhost", 11434),
            ("vLLM", "http://localhost", 8000),
            ("LM Studio", "http://localhost", 1234),
        ]
        for name, url, port in backends:
            try:
                import requests
                resp = requests.get(f"{url}:{port}/v1/models", timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    if models:
                        model_name = models[0].get("id", "")
                        _app_state["config"]["backend"] = name
                        _app_state["config"]["backend_url"] = url
                        _app_state["config"]["backend_port"] = port
                        _app_state["config"]["model"] = model_name
                        _log(f"Auto-scan found {name} with model {model_name}")
                        return {"ok": True, "backend": name, "model": model_name}
            except:
                continue
        return {"ok": False, "model": None}

    def _json_response(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

def main():
    port = 8080
    server = HTTPServer(("0.0.0.0", port), RequestHandler)
    print(f"=" * 60)
    print(f"  NetConnect Windows Sub Node")
    print(f"=" * 60)
    print(f"  Platform: Windows")
    print(f"  Open your browser and go to:")
    print(f"  http://localhost:{port}")
    print(f"=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()
