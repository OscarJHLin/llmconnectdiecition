#!/usr/bin/env python3
"""
NetConnect Central Compute Node - 独立安装包
包含中心计算节点功能，带Web UI管理控制台
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
from http.server import HTTPServer, BaseHTTPRequestHandler

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

_app_state = {
    "compute_node": None,
    "network_node": None,
    "config": {
        "backend": "Ollama",
        "url": "http://localhost",
        "port": 11434,
        "model": "",
        "node_name": "central-compute",
        "host": "0.0.0.0",
        "port_network": 8888,
        "multicast_group": "224.0.0.1",
        "multicast_port": 5000,
        "feishu": {"enabled": False, "app_id": "", "app_secret": ""},
        "weixin": {"enabled": False, "token": ""},
    },
    "status": {"node_running": False, "ai_connected": False},
    "logs": [],
    "chat_history": [],
    "tasks": [],
}


def _log(message):
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


class CentralNetworkNode:
    def __init__(self, host="0.0.0.0", port=8888, multicast_group="224.0.0.1", multicast_port=5000):
        self.host = host
        self.port = port
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.connected_nodes = {}
        self._server = None

    async def _handle_client(self, reader, writer):
        addr = writer.get_extra_info("peername")
        try:
            while True:
                length_data = await reader.readexactly(4)
                length = struct.unpack('!I', length_data)[0]
                data = await reader.readexactly(length)
                message = json.loads(data.decode('utf-8'))
                msg_type = message.get("type")

                if msg_type == "REGISTER":
                    node_id = str(uuid.uuid4())
                    self.connected_nodes[node_id] = {
                        "node_name": message.get("node_name"),
                        "node_type": message.get("node_type"),
                        "capabilities": message.get("capabilities", []),
                        "ip_address": addr[0],
                        "status": "online",
                    }
                    response = {"type": "REGISTER_RESPONSE", "status": "OK", "node_id": node_id}
                    self._send_message(writer, response)
                    _log(f"Node registered: {message.get('node_name')} ({addr[0]})")

                elif msg_type == "HEARTBEAT":
                    for nid, node in self.connected_nodes.items():
                        if node["ip_address"] == addr[0]:
                            node["status"] = "online"
                            break

                elif msg_type == "TASK_RESULT":
                    _log(f"Received task result from {addr[0]}")

        except:
            for nid, node in list(self.connected_nodes.items()):
                if node["ip_address"] == addr[0]:
                    del self.connected_nodes[nid]
                    _log(f"Node disconnected: {node.get('node_name', 'unknown')}")
                    break
            writer.close()

    def _send_message(self, writer, data):
        message = json.dumps(data).encode('utf-8')
        writer.write(struct.pack('!I', len(message)))
        writer.write(message)

    async def _discovery_server(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', self.multicast_port))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                        socket.inet_aton(self.multicast_group) + socket.inet_aton('0.0.0.0'))
        while True:
            data, addr = sock.recvfrom(1024)
            try:
                msg = json.loads(data.decode('utf-8'))
                if msg.get("type") == "DISCOVER":
                    response = {"type": "DISCOVER_RESPONSE", "port": self.port}
                    sock.sendto(json.dumps(response).encode('utf-8'), addr)
            except:
                pass

    async def start(self):
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        asyncio.create_task(self._discovery_server())
        _log(f"Central network node started on {self.host}:{self.port}")
        async with self._server:
            await self._server.serve_forever()


class CentralComputeNode:
    def __init__(self, node_name="central"):
        self.node_name = node_name
        self.tasks = {}

    async def submit_task(self, task_type, description, payload):
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = {
            "task_id": task_id,
            "task_type": task_type,
            "description": description,
            "payload": payload,
            "status": "pending",
        }
        _log(f"Task submitted: {task_id}")
        return task_id

    async def get_status(self):
        return {
            "connected": True,
            "tasks_pending": len([t for t in self.tasks.values() if t["status"] == "pending"]),
            "tasks_total": len(self.tasks),
            "available_nodes": len(_app_state.get("network_node", {}).connected_nodes if _app_state.get("network_node") else {}),
        }


HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NetConnect Central Dashboard</title>
<style>
:root { --bg: #1e1e2e; --fg: #cdd6f4; --accent: #89b4fa; --success: #a6e3a1; --error: #f38ba8; --surface: #313244; --border: #585b70; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg); }
.container { display: flex; height: 100vh; }
.sidebar { width: 200px; background: var(--surface); padding: 20px; border-right: 1px solid var(--border); }
.sidebar h1 { font-size: 16px; color: var(--accent); margin: 0 0 20px 0; }
.sidebar button { display: block; width: 100%; padding: 10px; margin-bottom: 8px; border: none; border-radius: 8px; background: transparent; color: var(--fg); text-align: left; cursor: pointer; }
.sidebar button.active { background: var(--accent); color: var(--bg); }
.main { flex: 1; padding: 20px; overflow-y: auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.header h2 { margin: 0; }
.badge { padding: 4px 12px; border-radius: 20px; font-size: 12px; }
.badge.success { background: rgba(166,227,161,0.2); color: var(--success); }
.badge.error { background: rgba(243,139,168,0.2); color: var(--error); }
.btn { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; }
.btn-primary { background: var(--accent); color: var(--bg); }
.btn-success { background: var(--success); color: var(--bg); }
.btn-danger { background: var(--error); color: var(--bg); }
.tab-content { display: none; }
.tab-content.active { display: block; }
.status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
.status-card { background: var(--surface); padding: 16px; border-radius: 8px; text-align: center; }
.status-card .label { font-size: 12px; color: #a6adc8; }
.status-card .value { font-size: 20px; font-weight: bold; margin-top: 4px; }
.chat-container { background: var(--surface); border-radius: 8px; overflow: hidden; height: 400px; display: flex; flex-direction: column; }
.chat-messages { flex: 1; padding: 16px; overflow-y: auto; }
.chat-message { margin-bottom: 12px; }
.chat-message.user .msg-content { background: var(--accent); color: var(--bg); }
.chat-message.assistant .msg-content { background: var(--border); }
.msg-content { padding: 10px 14px; border-radius: 16px; max-width: 80%; }
.chat-input { display: flex; padding: 12px; border-top: 1px solid var(--border); }
.chat-input input { flex: 1; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--fg); }
.chat-input button { padding: 10px 20px; background: var(--accent); color: var(--bg); border: none; border-radius: 8px; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 10px; text-align: left; border-bottom: 1px solid var(--border); }
.table th { background: var(--surface); }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; margin-bottom: 8px; }
.form-group input, .form-group select { width: 100%; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--fg); }
.log-panel { background: #111; padding: 12px; border-radius: 8px; height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px; white-space: pre-wrap; }
.gateway-section { background: var(--surface); padding: 20px; border-radius: 8px; margin-bottom: 16px; }
.gateway-section h3 { margin: 0 0 16px 0; color: var(--accent); }
</style>
</head>
<body>
<div class="container">
  <div class="sidebar">
    <h1>NetConnect</h1>
    <button class="active" onclick="showTab('chat')">聊天</button>
    <button onclick="showTab('nodes')">子节点监控</button>
    <button onclick="showTab('tasks')">任务管理</button>
    <button onclick="showTab('gateways')">消息网关</button>
    <button onclick="showTab('settings')">设置</button>
    <button onclick="showTab('logs')">日志</button>
  </div>
  <div class="main">
    <div class="header">
      <h2>中心计算节点控制台</h2>
      <div id="headerStatus" class="badge error">已停止</div>
    </div>

    <div id="chat" class="tab-content active">
      <div class="chat-container">
        <div class="chat-messages" id="chatMessages"></div>
        <div class="chat-input">
          <input type="text" id="chatInput" placeholder="输入消息..." onkeydown="if(event.keyCode===13) sendMessage()">
          <button onclick="sendMessage()">发送</button>
        </div>
      </div>
    </div>

    <div id="nodes" class="tab-content">
      <table class="table">
        <thead>
          <tr><th>节点名称</th><th>节点ID</th><th>类型</th><th>状态</th><th>能力</th></tr>
        </thead>
        <tbody id="nodesTable"></tbody>
      </table>
    </div>

    <div id="tasks" class="tab-content">
      <button class="btn btn-primary" onclick="showTaskForm()">提交任务</button>
      <div id="taskForm" style="display:none; margin-top:20px;" class="gateway-section">
        <h3>提交任务</h3>
        <div class="form-group">
          <label>任务类型</label>
          <select id="taskType">
            <option value="inference">推理</option>
            <option value="analysis">分析</option>
          </select>
        </div>
        <div class="form-group">
          <label>任务描述</label>
          <input type="text" id="taskDesc">
        </div>
        <button class="btn btn-success" onclick="submitTask()">提交</button>
      </div>
      <table class="table" style="margin-top:20px;">
        <thead>
          <tr><th>任务ID</th><th>类型</th><th>描述</th><th>状态</th></tr>
        </thead>
        <tbody id="tasksTable"></tbody>
      </table>
    </div>

    <div id="gateways" class="tab-content">
      <div class="gateway-section">
        <h3>飞书配置</h3>
        <label><input type="checkbox" id="feishuEnabled"> 启用飞书</label>
        <div class="form-group">
          <label>App ID</label>
          <input type="text" id="feishuAppId" placeholder="飞书机器人App ID">
        </div>
        <div class="form-group">
          <label>App Secret</label>
          <input type="text" id="feishuAppSecret" placeholder="飞书机器人App Secret">
        </div>
        <button class="btn btn-primary" onclick="saveFeishu()">保存配置</button>
      </div>
      <div class="gateway-section">
        <h3>微信配置</h3>
        <label><input type="checkbox" id="weixinEnabled"> 启用微信</label>
        <div class="form-group">
          <label>Token</label>
          <input type="text" id="weixinToken" placeholder="微信公众号Token">
        </div>
        <button class="btn btn-primary" onclick="saveWeixin()">保存配置</button>
      </div>
    </div>

    <div id="settings" class="tab-content">
      <div class="form-group">
        <label>AI后端</label>
        <select id="backendSelect">
          <option value="Ollama">Ollama</option>
          <option value="LM Studio">LM Studio</option>
          <option value="vLLM">vLLM</option>
        </select>
      </div>
      <div class="form-group">
        <label>节点名称</label>
        <input type="text" id="nodeName" value="central-compute">
      </div>
      <div class="form-group">
        <label>网络端口</label>
        <input type="number" id="netPort" value="8888">
      </div>
      <button class="btn btn-success" id="startBtn" onclick="startNode()">启动节点</button>
      <button class="btn btn-danger" id="stopBtn" onclick="stopNode()" disabled>停止节点</button>
    </div>

    <div id="logs" class="tab-content">
      <div class="log-panel" id="logPanel"></div>
    </div>
  </div>
</div>

<script>
let pollInterval;
function showTab(name) {
  document.querySelectorAll('.sidebar button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById(name).classList.add('active');
}
async function api(action, data={}) {
  const response = await fetch('/api', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action, ...data})
  });
  return response.json();
}
async function startNode() {
  const data = {
    node_name: document.getElementById('nodeName').value,
    network_port: parseInt(document.getElementById('netPort').value)
  };
  const result = await api('start_node', data);
  if (result.ok) {
    document.getElementById('startBtn').disabled = true;
    document.getElementById('stopBtn').disabled = false;
    document.getElementById('headerStatus').textContent = '运行中';
    document.getElementById('headerStatus').className = 'badge success';
    startPolling();
  }
}
async function stopNode() {
  await api('stop_node');
  document.getElementById('startBtn').disabled = false;
  document.getElementById('stopBtn').disabled = true;
  document.getElementById('headerStatus').textContent = '已停止';
  document.getElementById('headerStatus').className = 'badge error';
  stopPolling();
}
async function sendMessage() {
  const text = document.getElementById('chatInput').value.trim();
  if (!text) return;
  document.getElementById('chatInput').value = '';
  addChatMessage('user', text);
  const result = await api('chat', {message: text});
  addChatMessage('assistant', result.response);
}
function addChatMessage(role, content) {
  const el = document.getElementById('chatMessages');
  el.innerHTML += `<div class="chat-message ${role}"><div class="msg-content">${content}</div></div>`;
  el.scrollTop = el.scrollHeight;
}
function showTaskForm() {
  document.getElementById('taskForm').style.display = 'block';
}
async function submitTask() {
  const data = {
    task_type: document.getElementById('taskType').value,
    description: document.getElementById('taskDesc').value,
    payload: {}
  };
  await api('submit_task', data);
  document.getElementById('taskForm').style.display = 'none';
  document.getElementById('taskDesc').value = '';
}
async function saveFeishu() {
  const data = {
    enabled: document.getElementById('feishuEnabled').checked,
    app_id: document.getElementById('feishuAppId').value,
    app_secret: document.getElementById('feishuAppSecret').value
  };
  await api('save_feishu', data);
  alert('飞书配置已保存');
}
async function saveWeixin() {
  const data = {
    enabled: document.getElementById('weixinEnabled').checked,
    token: document.getElementById('weixinToken').value
  };
  await api('save_weixin', data);
  alert('微信配置已保存');
}
async function updateDashboard() {
  const nodes = await api('list_nodes');
  const tasks = await api('list_tasks');
  const status = await api('status');
  
  const nodesTable = document.getElementById('nodesTable');
  nodesTable.innerHTML = nodes.nodes.map(n => `
    <tr>
      <td>${n.node_name || '-'}</td>
      <td>${n.node_id || '-'}</td>
      <td>${n.node_type || '-'}</td>
      <td><span class="badge ${n.status === 'online' ? 'success' : 'error'}">${n.status}</span></td>
      <td>${n.capabilities?.join(', ') || '-'}</td>
    </tr>
  `).join('');

  const tasksTable = document.getElementById('tasksTable');
  tasksTable.innerHTML = tasks.tasks.map(t => `
    <tr>
      <td>${t.task_id?.substr(0,8) || '-'}</td>
      <td>${t.task_type || '-'}</td>
      <td>${t.description || '-'}</td>
      <td>${t.status || '-'}</td>
    </tr>
  `).join('');

  document.getElementById('logPanel').textContent = (status.logs || []).join('\\n');
}
function startPolling() {
  stopPolling();
  pollInterval = setInterval(updateDashboard, 2000);
  updateDashboard();
}
function stopPolling() {
  if (pollInterval) clearInterval(pollInterval);
}
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

    def _do_start_node(self, data):
        try:
            node_name = data.get("node_name") or "central-compute"
            network_port = int(data.get("network_port", 8888))

            compute = CentralComputeNode(node_name=node_name)
            network = CentralNetworkNode(port=network_port)

            _app_state["compute_node"] = compute
            _app_state["network_node"] = network
            _app_state["config"]["node_name"] = node_name
            _app_state["status"]["node_running"] = True
            _log("Central node starting...")

            def run_compute():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_forever()

            def run_network():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(network.start())

            threading.Thread(target=run_compute, daemon=True).start()
            threading.Thread(target=run_network, daemon=True).start()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_stop_node(self):
        _app_state["compute_node"] = None
        _app_state["network_node"] = None
        _app_state["status"]["node_running"] = False
        _log("Central node stopped")
        return {"ok": True}

    def _do_chat(self, data):
        text = data.get("message", "")
        _app_state["chat_history"].append({"role": "user", "content": text})
        response = f"Central AI received: {text}"
        _app_state["chat_history"].append({"role": "assistant", "content": response})
        return {"response": response}

    def _do_status(self):
        return {
            "status": _app_state["status"],
            "logs": _app_state["logs"][-50:],
        }

    def _do_list_nodes(self):
        network = _app_state.get("network_node")
        nodes = []
        if network:
            for nid, node in network.connected_nodes.items():
                nodes.append({
                    "node_id": nid,
                    "node_name": node.get("node_name"),
                    "node_type": node.get("node_type"),
                    "status": node.get("status"),
                    "capabilities": node.get("capabilities"),
                })
        return {"nodes": nodes}

    def _do_submit_task(self, data):
        compute = _app_state.get("compute_node")
        if not compute:
            return {"ok": False, "error": "Compute node not running"}
        try:
            future = _runner.run(compute.submit_task(
                data.get("task_type"),
                data.get("description"),
                data.get("payload", {})
            ))
            task_id = future.result(timeout=10)
            return {"ok": True, "task_id": task_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_list_tasks(self):
        compute = _app_state.get("compute_node")
        tasks = []
        if compute:
            for tid, task in compute.tasks.items():
                tasks.append({
                    "task_id": tid,
                    "task_type": task.get("task_type"),
                    "description": task.get("description"),
                    "status": task.get("status"),
                })
        return {"tasks": tasks}

    def _do_save_feishu(self, data):
        _app_state["config"]["feishu"].update({
            "enabled": bool(data.get("enabled")),
            "app_id": str(data.get("app_id", "")),
            "app_secret": str(data.get("app_secret", "")),
        })
        _log("Feishu config saved")
        return {"ok": True}

    def _do_save_weixin(self, data):
        _app_state["config"]["weixin"].update({
            "enabled": bool(data.get("enabled")),
            "token": str(data.get("token", "")),
        })
        _log("Weixin config saved")
        return {"ok": True}

    def _json_response(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def main():
    port = 8081
    server = HTTPServer(("0.0.0.0", port), RequestHandler)
    print(f"=" * 60)
    print(f"  NetConnect Central Compute Node")
    print(f"=" * 60)
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
