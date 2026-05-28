#!/usr/bin/env python3
"""
NetConnect Android Node - 独立安装包
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
        "tasks_completed": 0,
    },
    "logs": [],
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
    def __init__(self, node_name, multicast_group="224.0.0.1", multicast_port=5000):
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
                "capabilities": ["inference"]
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
                    if asyncio.iscoroutinefunction(self._message_handler):
                        await self._message_handler(message)
                    else:
                        self._message_handler(message)
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

    async def send_task_result(self, task_id, result):
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
    def __init__(self, node_name=None, capabilities=None):
        self.node_id = str(uuid.uuid4())
        self.node_name = node_name or f"hermes_node_{self.node_id[:8]}"
        self.capabilities = capabilities or ["inference"]
        self.agent_initialized = False
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

    async def _run_inference(self, prompt):
        return {"response": f"Processed: {prompt[:50]}..."}

    def get_status(self):
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "hermes_available": self.agent_initialized,
            "tasks_completed": len(self.task_history),
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
<title>NetConnect Android Node</title>
<style>
:root { --bg: #1e1e2e; --fg: #cdd6f4; --accent: #89b4fa; --success: #a6e3a1; --error: #f38ba8; --surface: #313244; }
body { margin: 0; font-family: sans-serif; background: var(--bg); color: var(--fg); padding: 16px; }
.header { text-align: center; margin-bottom: 24px; }
.header h1 { color: var(--accent); margin: 0; font-size: 20px; }
.header p { color: #a6adc8; font-size: 14px; }
.step { background: var(--surface); border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.step-title { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.step-number { width: 28px; height: 28px; border-radius: 50%; background: var(--accent); color: var(--bg); display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; }
.step h2 { margin: 0; font-size: 16px; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; margin-bottom: 6px; font-size: 14px; }
.form-group input { width: 100%; padding: 10px; border: 1px solid #585b70; border-radius: 8px; background: var(--bg); color: var(--fg); font-size: 14px; box-sizing: border-box; }
.btn { padding: 12px 20px; border: none; border-radius: 8px; font-size: 14px; font-weight: 500; width: 100%; margin-bottom: 8px; }
.btn-success { background: var(--success); color: var(--bg); }
.btn-danger { background: var(--error); color: var(--bg); }
.badge { padding: 4px 12px; border-radius: 20px; font-size: 12px; }
.badge.success { background: rgba(166,227,161,0.2); color: var(--success); }
.badge.error { background: rgba(243,139,168,0.2); color: var(--error); }
.status-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 16px; }
.status-card { background: var(--surface); padding: 12px; border-radius: 8px; text-align: center; }
.status-card .label { font-size: 12px; color: #a6adc8; }
.status-card .value { font-size: 16px; font-weight: bold; margin-top: 4px; }
.log-panel { background: #111; padding: 12px; border-radius: 8px; height: 150px; overflow-y: auto; font-family: monospace; font-size: 12px; white-space: pre-wrap; }
</style>
</head>
<body>
<div class="header">
  <h1>NetConnect Node</h1>
  <p>Android 子节点</p>
</div>

<div class="step">
  <div class="step-title">
    <div class="step-number">1</div>
    <h2>配置</h2>
  </div>
  <div class="form-group">
    <label>节点名称</label>
    <input type="text" id="nodeName">
  </div>
</div>

<div class="step">
  <div class="step-title">
    <div class="step-number">2</div>
    <h2>控制</h2>
  </div>
  <button class="btn btn-success" id="startBtn" onclick="startNode()">启动节点</button>
  <button class="btn btn-danger" id="stopBtn" onclick="stopNode()" disabled>停止节点</button>
  <div id="nodeStatus" class="badge error" style="display:block;text-align:center;margin-top:12px;">已停止</div>
</div>

<div class="step">
  <div class="step-title">
    <div class="step-number">3</div>
    <h2>状态</h2>
  </div>
  <div class="status-grid">
    <div class="status-card" id="routerStatus">
      <div class="label">路由器</div>
      <div class="value">未连接</div>
    </div>
    <div class="status-card" id="nodeStatusCard">
      <div class="label">节点状态</div>
      <div class="value">已停止</div>
    </div>
  </div>
  <div class="log-panel" id="logPanel"></div>
</div>

<script>
let pollInterval;
async function api(action, data={}) {
  const response = await fetch('/api', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action, ...data})
  });
  return response.json();
}
async function startNode() {
  const data = { node_name: document.getElementById('nodeName').value };
  const result = await api('start_node', data);
  if (result.ok) {
    document.getElementById('startBtn').disabled = true;
    document.getElementById('stopBtn').disabled = false;
    document.getElementById('nodeStatus').textContent = '运行中';
    document.getElementById('nodeStatus').className = 'badge success';
    startPolling();
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
async function updateStatus() {
  const result = await api('status');
  const s = result.status || {};
  const routerCard = document.getElementById('routerStatus');
  routerCard.querySelector('.value').textContent = s.router || '未连接';
  const nodeCard = document.getElementById('nodeStatusCard');
  nodeCard.querySelector('.value').textContent = s.ai_available ? '运行中' : '已停止';
  const logPanel = document.getElementById('logPanel');
  if (result.logs) {
    logPanel.textContent = result.logs.join('\\n');
    logPanel.scrollTop = logPanel.scrollHeight;
  }
}
function startPolling() {
  stopPolling();
  pollInterval = setInterval(updateStatus, 2000);
  updateStatus();
}
function stopPolling() {
  if (pollInterval) clearInterval(pollInterval);
}
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('nodeName').value = 'android-node-' + Math.random().toString(36).substr(2,6);
});
</script>
</body>
</html>
"""


class RequestHandler:
    def __init__(self, server):
        self.server = server

    def do_GET(self):
        self.server.send_response(200)
        self.server.send_header("Content-Type", "text/html; charset=utf-8")
        self.server.send_header("Cache-Control", "no-store")
        self.server.end_headers()
        self.server.wfile.write(HTML_PAGE.encode("utf-8"))

    def do_POST(self):
        content_len = int(self.server.headers.get("Content-Length", 0))
        body = self.server.rfile.read(content_len).decode("utf-8")
        try:
            data = json.loads(body)
        except:
            self._json_response({"error": "invalid json"}, 400)
            return
        action = data.get("action", "")
        result = self._process_action(action, data)
        self._json_response(result)

    def _process_action(self, action, data):
        if action == "start_node":
            return self._do_start_node(data)
        elif action == "stop_node":
            return self._do_stop_node()
        elif action == "status":
            return self._do_status()
        return {"error": "unknown action"}

    def _do_start_node(self, data):
        try:
            node_name = data.get("node_name") or _app_state["config"]["node_name"]
            hermes = HermesComputeNode(node_name=node_name, capabilities=["inference"])
            _app_state["hermes_node"] = hermes
            _app_state["network_client"] = hermes.network_client
            _app_state["config"]["node_name"] = node_name
            _log("Starting node...")

            def run_node():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(hermes.start())

            threading.Thread(target=run_node, daemon=True).start()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _do_stop_node(self):
        hermes = _app_state.get("hermes_node")
        if hermes:
            _runner.run(hermes.stop())
        _app_state["hermes_node"] = None
        _log("Node stopped")
        return {"ok": True}

    def _do_status(self):
        hermes = _app_state.get("hermes_node")
        net = _app_state.get("network_client")
        router_info = "Not discovered"
        if net:
            info = net.get_info()
            if info.get("connected"):
                router_info = f"{info.get('router_host')}:{info.get('router_port')}"
        ai_ok = False
        if hermes:
            ai_ok = hermes.get_status().get("hermes_available", False)
        return {
            "status": {
                "router": router_info,
                "ai_available": ai_ok,
                "node_name": _app_state["config"]["node_name"],
            },
            "logs": _app_state["logs"][-50:],
        }

    def _json_response(self, data, code=200):
        self.server.send_response(code)
        self.server.send_header("Content-Type", "application/json")
        self.server.send_header("Access-Control-Allow-Origin", "*")
        self.server.end_headers()
        self.server.wfile.write(json.dumps(data).encode("utf-8"))


def main():
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
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
            elif action == "status":
                return self._do_status()
            return {"error": "unknown action"}

        def _do_start_node(self, data):
            try:
                node_name = data.get("node_name") or _app_state["config"]["node_name"]
                hermes = HermesComputeNode(node_name=node_name, capabilities=["inference"])
                _app_state["hermes_node"] = hermes
                _app_state["network_client"] = hermes.network_client
                _app_state["config"]["node_name"] = node_name
                _log("Starting node...")

                def run_node():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(hermes.start())

                threading.Thread(target=run_node, daemon=True).start()
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        def _do_stop_node(self):
            hermes = _app_state.get("hermes_node")
            if hermes:
                _runner.run(hermes.stop())
            _app_state["hermes_node"] = None
            _log("Node stopped")
            return {"ok": True}

        def _do_status(self):
            hermes = _app_state.get("hermes_node")
            net = _app_state.get("network_client")
            router_info = "Not discovered"
            if net:
                info = net.get_info()
                if info.get("connected"):
                    router_info = f"{info.get('router_host')}:{info.get('router_port')}"
            ai_ok = False
            if hermes:
                ai_ok = hermes.get_status().get("hermes_available", False)
            return {
                "status": {
                    "router": router_info,
                    "ai_available": ai_ok,
                    "node_name": _app_state["config"]["node_name"],
                },
                "logs": _app_state["logs"][-50:],
            }

        def _json_response(self, data, code=200):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))

    port = 8080
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"NetConnect Android Node")
    print(f"Open http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
