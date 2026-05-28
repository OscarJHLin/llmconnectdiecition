import asyncio
import json
import uuid
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from enum import Enum

from central.ai.model_adapter import ModelAdapter, ModelBackend
from nodes.common.network.client_node import NetworkClient, get_platform, OSPlatform

class TaskStatus(Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"

class EdgeComputeNode:
    def __init__(self, node_name: str = None, 
                 ai_backend: ModelBackend = ModelBackend.OLLAMA,
                 ai_port: int = 11434,
                 capabilities: Optional[List[str]] = None):
        self.node_id = str(uuid.uuid4())
        self.node_name = node_name or f"edge_{self.node_id[:8]}"
        
        self.platform = get_platform()
        self.capabilities = capabilities or ["inference", "embedding"]
        
        self.network_client = NetworkClient(
            node_name=self.node_name,
            node_type="compute_node",
            capabilities=self.capabilities
        )
        
        self.ai_adapter = ModelAdapter(ai_backend, "http://localhost", ai_port)
        
        self.current_task: Optional[Dict] = None
        self.task_status = TaskStatus.IDLE
        self.task_history: List[Dict] = []
        
        self._running = False
        self._task_processor = None
        
        self.network_client.set_message_handler(self._handle_network_message)
        self.network_client.set_connection_callbacks(
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected
        )

    async def _handle_network_message(self, message: Dict):
        msg_type = message.get("type")
        
        if msg_type == "REGISTER_RESPONSE":
            print(f"Registered with network: {message}")
        
        elif msg_type == "TASK_ASSIGNMENT":
            await self._handle_task_assignment(message)
        
        elif msg_type == "FORWARDED_MESSAGE":
            content = message.get("content", {})
            if content.get("action") == "ping":
                await self._send_pong(message.get("source_id"))

    async def _on_connected(self, host: str, port: int):
        print(f"Connected to network at {host}:{port}")
        await self._request_task()

    def _on_disconnected(self):
        print("Disconnected from network")
        self.task_status = TaskStatus.IDLE

    async def _handle_task_assignment(self, message: Dict):
        if self.task_status == TaskStatus.PROCESSING:
            print("Busy, cannot accept new task")
            return
        
        self.task_status = TaskStatus.PROCESSING
        self.current_task = message
        
        print(f"Received task: {message.get('task_id')}")
        
        await self._process_task(message)

    async def _process_task(self, task: Dict):
        task_id = task.get("task_id")
        task_type = task.get("task_type")
        description = task.get("description")
        payload = task.get("payload", {})
        
        result = None
        try:
            if task_type == "inference":
                prompt = payload.get("prompt", description)
                result = await self.ai_adapter.generate(prompt)
            
            elif task_type == "embedding":
                text = payload.get("text", description)
                result = {"embedding": await self.ai_adapter.embeddings(text)}
            
            elif task_type == "analysis":
                data = payload.get("data", "")
                prompt = f"Analyze the following data:\n{data}"
                result = await self.ai_adapter.generate(prompt)
            
            else:
                result = {"error": f"Unknown task type: {task_type}"}
        
        except Exception as e:
            result = {"error": str(e)}
        
        self.task_status = TaskStatus.COMPLETED
        
        self.task_history.append({
            "task_id": task_id,
            "task_type": task_type,
            "timestamp": datetime.now().isoformat(),
            "result": result
        })
        
        await self._send_task_result(task_id, result)
        self.current_task = None
        
        await asyncio.sleep(1)
        await self._request_task()

    async def _send_task_result(self, task_id: str, result: Dict):
        result_message = {
            "type": "TASK_RESULT",
            "task_id": task_id,
            "node_id": self.node_id,
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
        await self.network_client.send_message(result_message)
        print(f"Sent result for task {task_id}")

    async def _request_task(self):
        if self.task_status == TaskStatus.IDLE:
            request = {
                "action": "request_task",
                "node_id": self.node_id,
                "status": self.task_status.value,
                "capabilities": self.capabilities,
                "platform": self.platform.value
            }
            await self.network_client.send_message(request)

    async def _send_pong(self, target_id: str):
        pong_message = {
            "type": "PONG",
            "node_id": self.node_id,
            "timestamp": datetime.now().isoformat()
        }
        await self.network_client.send_message(pong_message, target_id)

    async def run_local_inference(self, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
        return await self.ai_adapter.generate(prompt, model)

    async def _status_loop(self):
        while self._running:
            await asyncio.sleep(5)

    async def start(self):
        self._running = True
        print(f"Starting Edge Compute Node: {self.node_name} ({self.platform.value})")
        
        ai_available = await self.ai_adapter.health_check()
        if ai_available:
            models = await self.ai_adapter.list_models()
            if models:
                self.ai_adapter.set_default_model(models[0])
                print(f"AI backend available: {len(models)} models")
        else:
            print("AI backend not available, running in proxy mode")
        
        tasks = [
            asyncio.create_task(self.network_client.start()),
            asyncio.create_task(self._status_loop())
        ]
        
        await asyncio.gather(*tasks)

    async def stop(self):
        self._running = False
        await self.network_client.stop()
        print("Edge Compute Node stopped")

    async def get_status(self) -> Dict[str, Any]:
        ai_available = await self.ai_adapter.health_check()
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "platform": self.platform.value,
            "capabilities": self.capabilities,
            "task_status": self.task_status.value,
            "current_task": self.current_task.get("task_id") if self.current_task else None,
            "tasks_completed": len(self.task_history),
            "ai_available": ai_available,
            "connected": self.network_client.get_info().get("connected", False)
        }