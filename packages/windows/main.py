#!/usr/bin/env python3
"""
NetConnect Windows Node - 独立安装包
包含网络子节点和计算子节点功能
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

_app_state = {
    "hermes_node": None,
    "network_client": None,
    "config": {
        "backend": "Hermes",
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


class HermesComputeNode:
    def __init__(self, node_name: str = None, capabilities: List[str] = None):
        self.node_id = str(uuid.uuid4())
        self.node_name = node_name or f"hermes_node_{self.node_id[:8]}"
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
            try:
                import requests
                response = requests.post(
                    "http://localhost:11434/v1/chat/completions",
                    json={
                        "model": "llama3",
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False
                    },
                    timeout=60
                )
                if response.status_code == 200:
                    return {"response": response.json()["choices"][0]["message"]["content"]}
                return {"error": f"HTTP {response.status_code}"}
            except Exception as e:
                return {"error": str(e)}
        return {"response": "AI adapter not configured"}

    def get_status(self):
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "hermes_available": self.agent_initialized,
            "task_status": "idle",
            "tasks_completed": len(self.task_history),
            "capabilities": self.capabilities,
            "network_connected": self.network_client.connected
        }

    async def start(self):
        _log("Starting Hermes compute node...")
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
<title>NetConnect Node Installer - Windows</title>
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
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--fg); }
.container { max-width: 900px; margin: 0 auto; padding: 20px; }
.header { text-align: center; margin-bottom: 30px; }
.header h1 { color: var(--accent); margin: 0; }
.header p { color: #a6adc8; }
.step { background: var(--surface); border-radius: 12px; padding: 24px; margin-bottom: 20px; }
.step-title { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.step-number { width: 32px; height: 32px; border-radius: 50%; background: var(--accent); color: var(--bg); display: flex; align-items: center; justify-content: center; font-weight: bold; }
.step h2 { margin: 0; color: var(--fg); }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 8px; font-weight: 500; }
.form-group input, .form-group select { width: 100%; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--fg); font-size: 14px; }
.btn { padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; }
.btn-success { background: var(--success); color: var(--bg); }
.btn-danger { background: var(--error); color: var(--bg); }
.badge { padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; }
.badge.success { background: rgba(166, 227, 161, 0.2); color: var(--success); }
.badge.error { background: rgba(243, 139, 168, 0.2); color: var(--error); }
.status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
.status-card { background: var(--surface); padding: 16px; border-radius: 8px; text-align: center; }
.status-card .label { font-size: 12px; color: #a6adc8; }
.status-card .value { font-size: 18px; font-weight: bold; margin-top: 4px; }
.tab-container { display: flex; gap: 8px; margin-bottom: 16px; }
.tab { padding: 10px 20px; border: none; border-radius: 8px; background: var(--surface); color: var(--fg); cursor: pointer; }
.tab.active { background: var(--accent); color: var(--bg); }
.tab-content { display: none; }
.tab-content.active { display: block; }
.chat-container { background: var(--surface); border-radius: 8px; overflow: hidden; }
.chat-messages { height: 300px; overflow-y: auto; padding: 16px; }
.chat-message { margin-bottom: 12px; }
.chat-message.user .msg-content { background: var(--accent); color: var(--bg); }
.chat-message.assistant .msg-content { background: var(--border); }
.msg-content { padding: 10px 14px; border-radius: 16px; max-width: 80%; }
.chat-input { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--border); }
.chat-input input { flex: 1; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--fg); }
.chat-input button { padding: 10px 20px; background: var(--accent); color: var(--bg); border: none; border-radius: 8px; cursor: pointer; }
.log-panel { background: #11111b; padding: 12px; border-radius: 8px; height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px; white-space: pre-wrap; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>NetConnect Node Installer</h1>
    <p>Windows 子节点安装向导 - 网络+计算融合节点</p>
  </div>

  <div class="step">
    <div class="step-title">
      <div class="step-number">1</div>
      <h2>基本配置</h2>
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
      <div class="step-number">2</div>
      <h2>启动节点</h2>
    </div>
    <button class="btn btn-success" id="startBtn" onclick="startNode()">启动节点</button>
    <button class="btn btn-danger" id="stopBtn" onclick="stopNode()" disabled>停止节点</button>
    <div id="nodeStatus" class="badge" style="margin-left: 12px;">已停止</div>
  </div>

  <div class="step">
    <div class="step-title">
      <div class="step-number">3</div>
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
          <div class="value">Hermes</div>
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
async function startNode() {
  const data = {
    node_name: document.getElementById('nodeName').value,
    multicast_group: document.getElementById('multicastGroup').value,
    multicast_port: parseInt(document.getElementById('multicastPort').value)
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
  document.getElementById('chatInput').value = '';
  addChatMessage('user', text);
  const result = await api('chat', { message: text });
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
  const nodeCard = document.getElementById('nodeStatusCard');
  nodeCard.className = 'status-card ' + (s.ai_available ? 'success' : 'error');
  nodeCard.querySelector('.value').textContent = s.ai_available ? '运行中' : '已停止';
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
        return {"error": "unknown action"}

    def _do_start_node(self, data):
        try:
            node_name = data.get("node_name") or _app_state["config"]["node_name"]
            multicast_group = data.get("multicast_group", "224.0.0.1")
            multicast_port = int(data.get("multicast_port", 5000))

            hermes = HermesComputeNode(node_name=node_name, capabilities=["inference", "embedding", "analysis"])
            hermes.network_client.multicast_group = multicast_group
            hermes.network_client.multicast_port = multicast_port

            _app_state["hermes_node"] = hermes
            _app_state["network_client"] = hermes.network_client
            _app_state["config"].update({"node_name": node_name})
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

    def _do_stop_node(self):
        hermes = _app_state.get("hermes_node")
        if hermes:
            _runner.run(hermes.stop())
        _app_state["hermes_node"] = None
        _app_state["network_client"] = None
        _app_state["status"]["node_running"] = False
        _log("Node stopped")
        return {"ok": True}

    def _do_chat(self, data):
        text = data.get("message", "")
        hermes = _app_state.get("hermes_node")
        if hermes and hermes.agent_initialized:
            try:
                future = _runner.run(hermes._run_inference(text))
                response = future.result(timeout=60)
                return {"response": response.get("response", "No response")}
            except Exception as e:
                return {"response": f"[Error: {e}]"}
        else:
            return {"response": "Hermes Agent not initialized."}

    def _do_status(self):
        hermes = _app_state.get("hermes_node")
        net = _app_state.get("network_client")
        cfg = _app_state["config"]

        router_info = "Not discovered"
        if net:
            info = net.get_info()
            if info.get("connected"):
                router_info = f"{info.get('router_host')}:{info.get('router_port')}"

        ai_ok = False
        tasks_completed = 0

        if hermes:
            s = hermes.get_status()
            ai_ok = s.get("hermes_available", False)
            tasks_completed = s.get("tasks_completed", 0)

        return {
            "status": {
                "router": router_info,
                "backend": "Hermes Agent",
                "ai_available": ai_ok,
                "tasks_completed": tasks_completed,
                "node_name": cfg.get("node_name", "-"),
            },
            "logs": _app_state["logs"][-50:],
        }

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
    print(f"  NetConnect Windows Node")
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
