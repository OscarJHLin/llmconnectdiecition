import asyncio
import json
import uuid
from typing import Dict, List, Optional, Any, Set, Callable
from datetime import datetime
from enum import Enum
from dataclasses import dataclass

from central.ai.model_adapter import ModelAdapter, ModelBackend
from nodes.common.network.client_node import NetworkClient

class TaskStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class TaskType(Enum):
    INFERENCE = "inference"
    EMBEDDING = "embedding"
    ANALYSIS = "analysis"
    AGGREGATION = "aggregation"

@dataclass
class Task:
    task_id: str
    task_type: TaskType
    description: str
    payload: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    assigned_node: Optional[str] = None
    results: Dict[str, Any] = None
    created_at: float = None
    completed_at: Optional[float] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().timestamp()
        if self.results is None:
            self.results = {}

class CentralComputeNode:
    def __init__(self, node_name: str = "central_compute", 
                 ai_backend: ModelBackend = ModelBackend.OLLAMA,
                 ai_port: int = 11434):
        self.node_id = str(uuid.uuid4())
        self.node_name = node_name
        
        self.network_client = NetworkClient(
            node_name=node_name,
            node_type="compute_center",
            capabilities=["task_distribution", "result_aggregation", "model_inference"]
        )
        
        self.ai_adapter = ModelAdapter(ai_backend, "http://localhost", ai_port)
        
        self.tasks: Dict[str, Task] = {}
        self.task_queue = asyncio.Queue()
        self.available_nodes: Dict[str, Dict[str, Any]] = {}
        
        self._running = False
        self._task_processor = None
        self._node_monitor = None
        
        self.network_client.set_message_handler(self._handle_network_message)
        self.network_client.set_connection_callbacks(
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            on_message=self._on_message
        )

    async def _handle_network_message(self, message: Dict):
        msg_type = message.get("type")
        
        if msg_type == "REGISTER_RESPONSE":
            print(f"Registered with network: {message}")
        
        elif msg_type == "NODES_LIST":
            self._update_node_list(message.get("nodes", []))
        
        elif msg_type == "FORWARDED_MESSAGE":
            await self._handle_forwarded_message(message)
        
        elif msg_type == "TASK_RESULT":
            await self._handle_task_result(message)
        
        elif msg_type == "NODE_STATUS":
            await self._handle_node_status(message)

    async def _on_connected(self, host: str, port: int):
        print(f"Connected to network at {host}:{port}")
        await self._query_network_nodes()

    def _on_disconnected(self):
        print("Disconnected from network")

    def _on_message(self, message: Dict):
        print(f"Received message: {message}")

    async def _query_network_nodes(self):
        nodes = await self.network_client.query_nodes()
        if nodes:
            self._update_node_list(nodes.get("nodes", []))

    def _update_node_list(self, nodes: List[Dict]):
        for node in nodes:
            if node.get("node_type") == "compute_node":
                self.available_nodes[node["node_id"]] = node
        print(f"Available compute nodes: {list(self.available_nodes.keys())}")

    async def _handle_forwarded_message(self, message: Dict):
        content = message.get("content", {})
        if content.get("action") == "request_task":
            await self._assign_task(message.get("source_id"))

    async def _handle_task_result(self, message: Dict):
        task_id = message.get("task_id")
        node_id = message.get("node_id")
        result = message.get("result")
        
        if task_id in self.tasks:
            self.tasks[task_id].results[node_id] = result
            self.tasks[task_id].status = TaskStatus.COMPLETED
            self.tasks[task_id].completed_at = datetime.now().timestamp()
            
            print(f"Task {task_id} completed by {node_id}")
            await self._aggregate_results(task_id)

    async def _handle_node_status(self, message: Dict):
        node_id = message.get("node_id")
        status = message.get("status")
        
        if node_id in self.available_nodes:
            self.available_nodes[node_id]["status"] = status

    async def _assign_task(self, node_id: str):
        if self.task_queue.empty():
            return
        
        task = await self.task_queue.get()
        task.status = TaskStatus.ASSIGNED
        task.assigned_node = node_id
        
        task_message = {
            "type": "TASK_ASSIGNMENT",
            "task_id": task.task_id,
            "task_type": task.task_type.value,
            "description": task.description,
            "payload": task.payload,
            "timestamp": datetime.now().isoformat()
        }
        
        await self.network_client.send_message(task_message, node_id)
        print(f"Assigned task {task.task_id} to node {node_id}")

    async def _aggregate_results(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task:
            return
        
        results = list(task.results.values())
        if len(results) == 1:
            final_result = results[0]
        else:
            final_result = await self._fuse_results(results)
        
        task.results["aggregated"] = final_result
        print(f"Aggregated result for task {task_id}: {final_result}")

    async def _fuse_results(self, results: List[Dict]) -> Dict[str, Any]:
        fused = {
            "sources": len(results),
            "combined": []
        }
        
        for i, result in enumerate(results):
            fused["combined"].append({
                "source_index": i,
                "content": result.get("response", result)
            })
        
        prompt = f"Please aggregate and synthesize the following {len(results)} responses into a comprehensive answer:\n\n"
        for i, result in enumerate(results):
            prompt += f"{i+1}. {result.get('response', str(result))}\n\n"
        prompt += "Provide a unified, coherent summary."
        
        ai_result = await self.ai_adapter.generate(prompt)
        if isinstance(ai_result, dict) and "response" in ai_result:
            fused["summary"] = ai_result["response"]
        
        return fused

    async def submit_task(self, task_type: TaskType, description: str, payload: Optional[Dict] = None) -> str:
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            task_type=task_type,
            description=description,
            payload=payload or {}
        )
        
        self.tasks[task_id] = task
        await self.task_queue.put(task)
        
        print(f"Task submitted: {task_id} - {description}")
        return task_id

    async def run_local_inference(self, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
        return await self.ai_adapter.generate(prompt, model)

    async def get_task_status(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    async def _task_distribution_loop(self):
        while self._running:
            if not self.task_queue.empty() and self.available_nodes:
                available_node_ids = [
                    nid for nid, info in self.available_nodes.items()
                    if info.get("status") == "online"
                ]
                
                if available_node_ids:
                    for node_id in available_node_ids:
                        if not self.task_queue.empty():
                            await self._assign_task(node_id)
                        else:
                            break
            
            await asyncio.sleep(1)

    async def _monitor_loop(self):
        while self._running:
            await self._query_network_nodes()
            await asyncio.sleep(30)

    async def start(self):
        self._running = True
        print(f"Starting Central Compute Node: {self.node_name}")
        
        if await self.ai_adapter.health_check():
            models = await self.ai_adapter.list_models()
            if models:
                self.ai_adapter.set_default_model(models[0])
                print(f"AI backend connected. Available models: {models}")
        else:
            print("Warning: AI backend not available")
        
        tasks = [
            asyncio.create_task(self.network_client.start()),
            asyncio.create_task(self._task_distribution_loop()),
            asyncio.create_task(self._monitor_loop())
        ]
        
        await asyncio.gather(*tasks)

    async def stop(self):
        self._running = False
        await self.network_client.stop()
        print("Central Compute Node stopped")

    async def get_status(self) -> Dict[str, Any]:
        ai_connected = await self.ai_adapter.health_check()
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "tasks_pending": self.task_queue.qsize(),
            "tasks_total": len(self.tasks),
            "available_nodes": len(self.available_nodes),
            "ai_connected": ai_connected,
            "connected": self.network_client.get_info().get("connected", False)
        }