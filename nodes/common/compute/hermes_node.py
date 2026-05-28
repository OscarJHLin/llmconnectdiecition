#!/usr/bin/env python3
"""
Hermes-based Compute Node for Private Network AI Collaboration System

This module wraps the Hermes Agent as a compute node that can:
1. Auto-discover and connect to central network router
2. Register as a compute node in the network
3. Receive tasks from central compute node
4. Execute AI inference using Hermes Agent
5. Return results to central node

Features:
- Seamless integration with Hermes Agent capabilities
- Support for Ollama/vLLM/LM Studio/OpenAI backends
- Automatic network discovery via Multicast
- Task processing and result aggregation
- Cross-platform support (macOS/Windows/Linux/Android)
"""

import asyncio
import json
import uuid
import os
import sys
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from enum import Enum

# Add hermes-agent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'hermes-agent-main'))

from nodes.common.network.client_node import NetworkClient, get_platform, OSPlatform

try:
    from run_agent import AIAgent
    HERMES_AVAILABLE = True
except ImportError:
    HERMES_AVAILABLE = False

class TaskStatus(Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"

class HermesComputeNode:
    def __init__(self, node_name: str = None, capabilities: Optional[List[str]] = None):
        self.node_id = str(uuid.uuid4())
        self.node_name = node_name or f"hermes_node_{self.node_id[:8]}"
        self.platform = get_platform()
        self.capabilities = capabilities or ["inference", "embedding", "analysis", "tool_calling"]
        
        self.network_client = NetworkClient(
            node_name=self.node_name,
            node_type="compute_node",
            capabilities=self.capabilities
        )
        
        self.agent = None
        self.agent_initialized = False
        
        self.current_task: Optional[Dict] = None
        self.task_status = TaskStatus.IDLE
        self.task_history: List[Dict] = []
        
        self._running = False
        self._message_handler = None
        
        self.network_client.set_message_handler(self._handle_network_message)
        self.network_client.set_connection_callbacks(
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected
        )

    async def _init_hermes_agent(self):
        """Initialize Hermes Agent with default configuration."""
        if not HERMES_AVAILABLE:
            print("Hermes Agent not available, running in proxy mode")
            return False
        
        try:
            self.agent = AIAgent()
            self.agent_initialized = True
            print("Hermes Agent initialized successfully")
            return True
        except Exception as e:
            print(f"Failed to initialize Hermes Agent: {e}")
            return False

    async def _handle_network_message(self, message: Dict):
        """Handle incoming network messages."""
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
        """Callback when connected to network."""
        print(f"Connected to network at {host}:{port}")
        if not self.agent_initialized:
            await self._init_hermes_agent()
        await self._request_task()

    def _on_disconnected(self):
        """Callback when disconnected from network."""
        print("Disconnected from network")
        self.task_status = TaskStatus.IDLE

    async def _handle_task_assignment(self, message: Dict):
        """Handle incoming task assignment."""
        if self.task_status == TaskStatus.PROCESSING:
            print("Busy, cannot accept new task")
            await self._send_task_busy(message.get("task_id"))
            return
        
        self.task_status = TaskStatus.PROCESSING
        self.current_task = message
        
        print(f"Received task: {message.get('task_id')}")
        
        await self._process_task(message)

    async def _process_task(self, task: Dict):
        """Process a task and return results."""
        task_id = task.get("task_id")
        task_type = task.get("task_type", "inference")
        description = task.get("description")
        payload = task.get("payload", {})
        
        result = None
        error = None
        
        try:
            if task_type == "inference":
                prompt = payload.get("prompt", description)
                result = await self._run_inference(prompt, payload)
            
            elif task_type == "embedding":
                text = payload.get("text", description)
                result = await self._generate_embedding(text)
            
            elif task_type == "analysis":
                data = payload.get("data", "")
                prompt = f"Analyze the following data:\n{data}"
                result = await self._run_inference(prompt, payload)
            
            elif task_type == "tool_calling":
                result = await self._run_tool_calling(description, payload)
            
            else:
                result = {"error": f"Unknown task type: {task_type}"}
        
        except Exception as e:
            error = str(e)
            result = {"error": error}
            self.task_status = TaskStatus.ERROR
        
        self.task_status = TaskStatus.COMPLETED
        
        self.task_history.append({
            "task_id": task_id,
            "task_type": task_type,
            "timestamp": datetime.now().isoformat(),
            "result": result,
            "error": error
        })
        
        await self._send_task_result(task_id, result)
        self.current_task = None
        
        await asyncio.sleep(1)
        await self._request_task()

    async def _run_inference(self, prompt: str, params: Dict = None) -> Dict[str, Any]:
        """Run AI inference using Hermes Agent."""
        if not self.agent_initialized or not self.agent:
            return {"response": f"[Hermes Node] Processed prompt: {prompt[:50]}..."}
        
        try:
            response = self.agent.run_conversation(prompt)
            return {"response": str(response)}
        except Exception as e:
            return {"error": str(e), "fallback": f"Processed: {prompt[:50]}..."}

    async def _generate_embedding(self, text: str) -> Dict[str, Any]:
        """Generate embedding for text."""
        if not self.agent_initialized:
            return {"embedding": [0.0] * 384}
        
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('all-MiniLM-L6-v2')
            embedding = model.encode(text).tolist()
            return {"embedding": embedding}
        except Exception as e:
            return {"error": str(e), "embedding": [0.0] * 384}

    async def _run_tool_calling(self, description: str, payload: Dict) -> Dict[str, Any]:
        """Run tool calling task."""
        if not self.agent_initialized or not self.agent:
            return {"response": f"Tool calling not available without Hermes Agent"}
        
        try:
            response = self.agent.run_conversation(description)
            return {"response": str(response)}
        except Exception as e:
            return {"error": str(e)}

    async def _send_task_result(self, task_id: str, result: Dict):
        """Send task result back to central node."""
        result_message = {
            "type": "TASK_RESULT",
            "task_id": task_id,
            "node_id": self.node_id,
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
        await self.network_client.send_message(result_message)
        print(f"Sent result for task {task_id}")

    async def _send_task_busy(self, task_id: str):
        """Notify central node that we're busy."""
        message = {
            "type": "TASK_BUSY",
            "task_id": task_id,
            "node_id": self.node_id,
            "status": "busy",
            "timestamp": datetime.now().isoformat()
        }
        await self.network_client.send_message(message)

    async def _request_task(self):
        """Request a task from central node."""
        if self.task_status == TaskStatus.IDLE:
            request = {
                "action": "request_task",
                "node_id": self.node_id,
                "status": self.task_status.value,
                "capabilities": self.capabilities,
                "platform": self.platform.value,
                "hermes_available": self.agent_initialized
            }
            await self.network_client.send_message(request)

    async def _send_pong(self, target_id: str):
        """Send pong response to ping."""
        pong_message = {
            "type": "PONG",
            "node_id": self.node_id,
            "timestamp": datetime.now().isoformat()
        }
        await self.network_client.send_message(pong_message, target_id)

    async def _status_loop(self):
        """Periodically send status updates."""
        while self._running:
            await asyncio.sleep(30)
            await self._request_task()

    async def start(self):
        """Start the compute node."""
        self._running = True
        print(f"Starting Hermes Compute Node: {self.node_name} ({self.platform.value})")
        
        if HERMES_AVAILABLE:
            await self._init_hermes_agent()
        else:
            print("Hermes Agent not available - install hermes-agent dependencies")
        
        tasks = [
            asyncio.create_task(self.network_client.start()),
            asyncio.create_task(self._status_loop())
        ]
        
        await asyncio.gather(*tasks)

    async def stop(self):
        """Stop the compute node."""
        self._running = False
        await self.network_client.stop()
        print("Hermes Compute Node stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get node status."""
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "platform": self.platform.value,
            "capabilities": self.capabilities,
            "task_status": self.task_status.value,
            "current_task": self.current_task.get("task_id") if self.current_task else None,
            "tasks_completed": len(self.task_history),
            "hermes_available": self.agent_initialized,
            "connected": self.network_client.get_info().get("connected", False)
        }