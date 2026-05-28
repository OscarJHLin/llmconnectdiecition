#!/usr/bin/env python3
"""
子节点可视化程序 - 计算与网络合一
功能：
- AI后端自动识别与选择
- 网络配置可视化
- 网络连接状态监控
- 一键启动/停止
"""

import asyncio
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import json
import socket
import requests
from datetime import datetime
from typing import Dict, List, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from central.ai.model_adapter import ModelAdapter, ModelBackend
from nodes.common.network.client_node import NetworkClient, get_platform, OSPlatform


class AutoDetectBackend:
    """自动识别本地AI后端"""

    BACKENDS = [
        {"name": "Ollama", "port": 11434, "type": "ollama", "endpoint": "/api/tags"},
        {"name": "vLLM", "port": 8000, "type": "vllm", "endpoint": "/v1/models"},
        {"name": "LM Studio", "port": 1234, "type": "lm_studio", "endpoint": "/v1/models"},
    ]

    @staticmethod
    def detect() -> List[Dict]:
        """扫描本地可用的AI后端"""
        found = []
        for backend in AutoDetectBackend.BACKENDS:
            try:
                url = f"http://localhost:{backend['port']}{backend['endpoint']}"
                response = requests.get(url, timeout=2)
                if response.status_code == 200:
                    models = []
                    data = response.json()
                    if backend['type'] == 'ollama':
                        models = [m['name'] for m in data.get('models', [])]
                    else:
                        models = [m.get('id', m.get('name', 'unknown')) for m in data.get('data', [])]
                    found.append({
                        "name": backend['name'],
                        "type": backend['type'],
                        "port": backend['port'],
                        "models": models[:5],
                        "model_count": len(models)
                    })
            except:
                pass
        return found


class UnifiedNode:
    """合并的计算+网络子节点"""

    def __init__(self, node_name: str, ai_backend: ModelBackend, ai_port: int,
                 router_host: Optional[str] = None, router_port: Optional[int] = None):
        self.node_id = None
        self.node_name = node_name
        self.platform = get_platform()
        self.ai_adapter = ModelAdapter(ai_backend, "http://localhost", ai_port)
        self.network_client = NetworkClient(
            node_name=node_name,
            node_type="compute_node",
            capabilities=["inference", "embedding"]
        )
        # 如果指定了路由器地址，覆盖自动发现
        if router_host:
            self.network_client.router_host = router_host
        if router_port:
            self.network_client.router_port = router_port

        self._running = False
        self._task = None
        self.on_status_change = None
        self.on_log = None

    async def _handle_message(self, message: Dict):
        msg_type = message.get("type")
        if msg_type == "REGISTER_RESPONSE":
            self._log(f"已注册到网络: {message.get('message', 'success')}")
            if self.on_status_change:
                self.on_status_change("connected", True)
        elif msg_type == "TASK_ASSIGNMENT":
            await self._process_task(message)

    async def _process_task(self, task: Dict):
        task_id = task.get("task_id")
        task_type = task.get("task_type", "inference")
        payload = task.get("payload", {})
        self._log(f"收到任务: {task_id} ({task_type})")

        try:
            if task_type == "inference":
                prompt = payload.get("prompt", task.get("description", ""))
                result = await self.ai_adapter.generate(prompt)
            elif task_type == "embedding":
                text = payload.get("text", "")
                result = {"embedding": await self.ai_adapter.embeddings(text)}
            else:
                result = {"error": f"未知任务类型: {task_type}"}
        except Exception as e:
            result = {"error": str(e)}

        # 发送结果
        result_msg = {
            "type": "TASK_RESULT",
            "task_id": task_id,
            "node_id": self.node_id,
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
        await self.network_client.send_message(result_msg)
        self._log(f"任务 {task_id} 完成")

    def _log(self, msg: str):
        if self.on_log:
            self.on_log(msg)

    async def start(self):
        self._running = True
        self.node_id = self.network_client.node_id
        self.network_client.set_message_handler(self._handle_message)

        # AI健康检查
        ai_ok = await self.ai_adapter.health_check()
        if ai_ok:
            models = await self.ai_adapter.list_models()
            if models:
                self.ai_adapter.set_default_model(models[0])
            self._log(f"AI后端就绪: {len(models)} 个模型")
        else:
            self._log("警告: AI后端未连接")

        self._log(f"启动节点: {self.node_name} ({self.platform.value})")
        await self.network_client.start()

    async def stop(self):
        self._running = False
        await self.network_client.stop()
        self._log("节点已停止")

    def get_status(self) -> Dict:
        info = self.network_client.get_info()
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "platform": self.platform.value,
            "connected": info.get("connected", False),
            "router": f"{info.get('router_host')}:{info.get('router_port')}",
            "ai_backend": self.ai_adapter.backend.value,
            "ai_port": self.ai_adapter.port,
            "default_model": self.ai_adapter._default_model or "未设置"
        }


class NodeGUI:
    """子节点可视化界面"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI协作网络 - 子节点")
        self.root.geometry("700x600")
        self.root.configure(bg="#1e1e2e")

        self.node: Optional[UnifiedNode] = None
        self.node_thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        self._build_ui()
        self._auto_detect()

    def _build_ui(self):
        # 样式
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Microsoft YaHei", 10))
        style.configure("TButton", font=("Microsoft YaHei", 10), padding=5)
        style.configure("Title.TLabel", font=("Microsoft YaHei", 16, "bold"), foreground="#89b4fa")
        style.configure("Status.TLabel", font=("Microsoft YaHei", 11), foreground="#a6e3a1")
        style.configure("Error.TLabel", font=("Microsoft YaHei", 11), foreground="#f38ba8")

        # 标题
        title = ttk.Label(self.root, text="AI协作网络 - 子节点控制台", style="Title.TLabel")
        title.pack(pady=15)

        # 主容器
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # === AI后端配置 ===
        ai_frame = tk.LabelFrame(main_frame, text="AI后端配置", bg="#313244", fg="#cdd6f4",
                                  font=("Microsoft YaHei", 11, "bold"), padx=10, pady=10)
        ai_frame.pack(fill=tk.X, pady=5)

        ttk.Label(ai_frame, text="后端类型:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.backend_var = tk.StringVar(value="ollama")
        self.backend_combo = ttk.Combobox(ai_frame, textvariable=self.backend_var,
                                           values=["ollama", "vllm", "lm_studio", "openai"],
                                           state="readonly", width=15)
        self.backend_combo.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(ai_frame, text="端口:").grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        self.port_var = tk.StringVar(value="11434")
        self.port_entry = ttk.Entry(ai_frame, textvariable=self.port_var, width=10)
        self.port_entry.grid(row=0, column=3, sticky=tk.W, padx=5)

        self.detect_btn = ttk.Button(ai_frame, text="自动识别", command=self._auto_detect)
        self.detect_btn.grid(row=0, column=4, padx=(20, 0))

        self.detect_result = ttk.Label(ai_frame, text="", foreground="#a6e3a1")
        self.detect_result.grid(row=1, column=0, columnspan=5, sticky=tk.W, pady=5)

        # === 网络配置 ===
        net_frame = tk.LabelFrame(main_frame, text="网络配置", bg="#313244", fg="#cdd6f4",
                                   font=("Microsoft YaHei", 11, "bold"), padx=10, pady=10)
        net_frame.pack(fill=tk.X, pady=5)

        ttk.Label(net_frame, text="节点名称:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.name_var = tk.StringVar(value=f"node_{socket.gethostname()}")
        ttk.Entry(net_frame, textvariable=self.name_var, width=25).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(net_frame, text="路由器地址:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.router_host_var = tk.StringVar(value="")
        ttk.Entry(net_frame, textvariable=self.router_host_var, width=15).grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Label(net_frame, text="(留空自动发现)").grid(row=1, column=2, sticky=tk.W)

        ttk.Label(net_frame, text="路由器端口:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.router_port_var = tk.StringVar(value="8888")
        ttk.Entry(net_frame, textvariable=self.router_port_var, width=10).grid(row=2, column=1, sticky=tk.W, padx=5)

        # === 状态监控 ===
        status_frame = tk.LabelFrame(main_frame, text="运行状态", bg="#313244", fg="#cdd6f4",
                                      font=("Microsoft YaHei", 11, "bold"), padx=10, pady=10)
        status_frame.pack(fill=tk.X, pady=5)

        self.status_label = ttk.Label(status_frame, text="状态: 未启动", style="Error.TLabel")
        self.status_label.pack(anchor=tk.W, pady=2)

        self.network_label = ttk.Label(status_frame, text="网络: 未连接")
        self.network_label.pack(anchor=tk.W, pady=2)

        self.ai_label = ttk.Label(status_frame, text="AI后端: 未配置")
        self.ai_label.pack(anchor=tk.W, pady=2)

        self.platform_label = ttk.Label(status_frame, text=f"平台: {get_platform().value}")
        self.platform_label.pack(anchor=tk.W, pady=2)

        # === 控制按钮 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        self.start_btn = tk.Button(btn_frame, text="启动节点", bg="#a6e3a1", fg="#1e1e2e",
                                    font=("Microsoft YaHei", 12, "bold"), width=12,
                                    command=self._start_node)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = tk.Button(btn_frame, text="停止节点", bg="#f38ba8", fg="#1e1e2e",
                                   font=("Microsoft YaHei", 12, "bold"), width=12,
                                   command=self._stop_node, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.refresh_btn = ttk.Button(btn_frame, text="刷新状态", command=self._refresh_status)
        self.refresh_btn.pack(side=tk.LEFT, padx=5)

        # === 日志输出 ===
        log_frame = tk.LabelFrame(main_frame, text="运行日志", bg="#313244", fg="#cdd