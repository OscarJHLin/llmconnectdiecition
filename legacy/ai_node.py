import asyncio
import json
import time
import uuid
from typing import Dict, Any, List, Optional, Callable

from .protocol import (
    BaseMessage, MessageType, NodeInfo,
    TaskRequest, TaskResponse, DiscussionMessage
)
from .communication import WebSocketClient
from .memory import MemoryManager, ConversationHistory


class AINode:
    def __init__(
        self,
        node_name: str,
        specialty: str,
        memory_db_path: str,
        coordinator_uri: str,
        capabilities: Optional[List[str]] = None
    ):
        self.node_id = str(uuid.uuid4())
        self.node_info = NodeInfo(
            node_id=self.node_id,
            node_name=node_name,
            specialty=specialty,
            capabilities=capabilities or [],
            status="active"
        )

        self.memory = MemoryManager(memory_db_path, f"memory_{self.node_id}")
        self.conversation_history = ConversationHistory()

        self.client = WebSocketClient(self.node_info, coordinator_uri)
        self._setup_message_handlers()

        self.task_callbacks: Dict[str, Callable] = {}
        self.current_discussion: Optional[str] = None

    def _setup_message_handlers(self):
        self.client.message_handler.register_handler(
            MessageType.TASK_REQUEST,
            self._handle_task_request
        )
        self.client.message_handler.register_handler(
            MessageType.DISCUSSION_MESSAGE,
            self._handle_discussion_message
        )
        self.client.message_handler.register_handler(
            MessageType.COORDINATION_COMMAND,
            self._handle_coordination_command
        )
        self.client.message_handler.register_handler(
            MessageType.HEARTBEAT,
            self._handle_heartbeat
        )

    async def _handle_task_request(self, message: BaseMessage):
        try:
            task_request = TaskRequest(**message.payload)
            self.conversation_history.add_message(
                "system",
                f"Received task: {task_request.task_description}",
                {"task_id": task_request.task_id}
            )

            result = await self.process_task(task_request)

            response = TaskResponse(
                task_id=task_request.task_id,
                responder_id=self.node_id,
                status="completed",
                result=result,
                confidence=0.85
            )

            response_msg = self.client.create_message(
                MessageType.TASK_RESPONSE,
                response.model_dump()
            )
            await self.client.send_message(response_msg)

        except Exception as e:
            error_response = TaskResponse(
                task_id=message.payload.get('task_id', 'unknown'),
                responder_id=self.node_id,
                status="error",
                error=str(e)
            )
            response_msg = self.client.create_message(
                MessageType.TASK_RESPONSE,
                error_response.model_dump()
            )
            await self.client.send_message(response_msg)

    async def _handle_discussion_message(self, message: BaseMessage):
        try:
            disc_msg = DiscussionMessage(**message.payload)

            if disc_msg.discussion_id != self.current_discussion:
                self.current_discussion = disc_msg.discussion_id

            self.conversation_history.add_message(
                "peer",
                disc_msg.content,
                {
                    "discussion_id": disc_msg.discussion_id,
                    "sender_id": message.sender_id,
                    "message_index": disc_msg.message_index
                }
            )

            response_content = await self.generate_discussion_response(disc_msg)

            if response_content:
                my_response = DiscussionMessage(
                    discussion_id=disc_msg.discussion_id,
                    message_index=disc_msg.message_index + 1,
                    content=response_content,
                    agreement=0.9
                )

                response_msg = self.client.create_message(
                    MessageType.DISCUSSION_MESSAGE,
                    my_response.model_dump()
                )
                await self.client.send_message(response_msg)

        except Exception as e:
            print(f"Error handling discussion: {e}")

    async def _handle_coordination_command(self, message: BaseMessage):
        print(f"Received coordination command: {message.payload}")

    async def _handle_heartbeat(self, message: BaseMessage):
        heartbeat_msg = self.client.create_message(
            MessageType.HEARTBEAT,
            {"status": "alive"}
        )
        await self.client.send_message(heartbeat_msg)

    async def process_task(self, task_request: TaskRequest) -> Dict[str, Any]:
        relevant_memories = self.memory.search_memories(
            task_request.task_description,
            top_k=5
        )

        prompt = self._build_prompt(task_request, relevant_memories)
        response = await self._generate_response(prompt)

        self.memory.add_memory(
            f"Task: {task_request.task_description}\nResponse: {response}",
            {"task_id": task_request.task_id, "type": "task_result"}
        )

        return {
            "answer": response,
            "memories_used": len(relevant_memories),
            "specialty": self.node_info.specialty
        }

    def _build_prompt(self, task_request: TaskRequest, memories: List[Dict]) -> str:
        prompt = f"Task: {task_request.task_description}\n"
        prompt += f"Specialty: {self.node_info.specialty}\n\n"

        if memories:
            prompt += "Relevant memories:\n"
            for i, mem in enumerate(memories, 1):
                prompt += f"{i}. {mem['content']}\n"

        return prompt

    async def _generate_response(self, prompt: str) -> str:
        await asyncio.sleep(0.1)
        return f"[AI Node {self.node_info.specialty}] Processed: {prompt[:50]}..."

    async def generate_discussion_response(self, disc_msg: DiscussionMessage) -> str:
        await asyncio.sleep(0.1)
        return f"[Node {self.node_info.specialty}] I have a different perspective..."

    def add_knowledge(self, content: str, metadata: Optional[Dict] = None):
        self.memory.add_memory(content, metadata)

    async def start(self):
        print(f"Starting AI Node {self.node_id} ({self.node_info.specialty})")
        await self.client.start()

    async def stop(self):
        await self.client.stop()
