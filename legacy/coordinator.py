import asyncio
import uuid
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

from .protocol import (
    BaseMessage, MessageType, NodeInfo,
    TaskRequest, TaskResponse, DiscussionMessage,
    CoordinationCommand
)
from .communication import WebSocketServer


class TaskState:
    def __init__(self, task_id: str, task_request: TaskRequest):
        self.task_id = task_id
        self.task_request = task_request
        self.responses: Dict[str, TaskResponse] = {}
        self.start_time = asyncio.get_event_loop().time()
        self.completed = False
        self.result: Optional[Dict[str, Any]] = None


class DiscussionState:
    def __init__(self, discussion_id: str, topic: str, participants: Set[str]):
        self.discussion_id = discussion_id
        self.topic = topic
        self.participants = participants
        self.messages: List[Dict[str, Any]] = []
        self.current_round = 0
        self.summary: Optional[str] = None


class Coordinator:
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.coordinator_id = str(uuid.uuid4())
        self.node_info = NodeInfo(
            node_id=self.coordinator_id,
            node_name="coordinator",
            specialty="coordination",
            capabilities=["task_distribution", "discussion_management"]
        )

        self.server = WebSocketServer(host, port, self.node_info)
        self._setup_message_handlers()

        self.tasks: Dict[str, TaskState] = {}
        self.discussions: Dict[str, DiscussionState] = {}
        self.connected_nodes: Dict[str, NodeInfo] = {}

    def _setup_message_handlers(self):
        self.server.message_handler.register_handler(
            MessageType.HELLO,
            self._handle_hello
        )
        self.server.message_handler.register_handler(
            MessageType.TASK_RESPONSE,
            self._handle_task_response
        )
        self.server.message_handler.register_handler(
            MessageType.DISCUSSION_MESSAGE,
            self._handle_discussion_message
        )

    async def _handle_hello(self, message: BaseMessage, **kwargs):
        client_id = kwargs.get('client_id')
        if client_id:
            node_info = NodeInfo(**message.payload['node_info'])
            self.connected_nodes[client_id] = node_info
            print(f"Node registered: {node_info.node_name} ({node_info.specialty})")

    async def _handle_task_response(self, message: BaseMessage, **kwargs):
        try:
            response = TaskResponse(**message.payload)
            task_id = response.task_id

            if task_id in self.tasks:
                task_state = self.tasks[task_id]
                task_state.responses[response.responder_id] = response

                print(f"Received response from {response.responder_id} for task {task_id}")

                if self._check_task_complete(task_state):
                    await self._finalize_task(task_state)

        except Exception as e:
            print(f"Error handling task response: {e}")

    async def _handle_discussion_message(self, message: BaseMessage, **kwargs):
        try:
            disc_msg = DiscussionMessage(**message.payload)
            discussion_id = disc_msg.discussion_id

            if discussion_id in self.discussions:
                disc_state = self.discussions[discussion_id]
                disc_state.messages.append({
                    'sender_id': message.sender_id,
                    'content': disc_msg.content,
                    'timestamp': message.timestamp,
                    'agreement': disc_msg.agreement
                })

                print(f"Discussion message received: {disc_msg.content[:50]}...")

        except Exception as e:
            print(f"Error handling discussion message: {e}")

    def _check_task_complete(self, task_state: TaskState) -> bool:
        required_responders = self._get_eligible_nodes(task_state.task_request)
        received_responders = set(task_state.responses.keys())
        return received_responders.issuperset(required_responders) or \
               (asyncio.get_event_loop().time() - task_state.start_time > 30)

    def _get_eligible_nodes(self, task_request: TaskRequest) -> Set[str]:
        eligible = set()
        for node_id, node_info in self.connected_nodes.items():
            if task_request.requirements:
                if any(req in node_info.capabilities for req in task_request.requirements):
                    eligible.add(node_id)
            else:
                eligible.add(node_id)
        return eligible

    async def _finalize_task(self, task_state: TaskState):
        task_state.completed = True

        aggregated_result = self._aggregate_responses(task_state)
        task_state.result = aggregated_result

        print(f"Task {task_state.task_id} completed. Result: {aggregated_result}")

    def _aggregate_responses(self, task_state: TaskState) -> Dict[str, Any]:
        responses = list(task_state.responses.values())

        if not responses:
            return {'error': 'No responses received'}

        best_response = max(
            responses,
            key=lambda r: r.confidence or 0
        )

        return {
            'best_answer': best_response.result,
            'all_responses': [r.result for r in responses],
            'consensus': len(responses) > 1,
            'responders': list(task_state.responses.keys())
        }

    async def submit_task(self, task_description: str, task_type: str = "general",
                         requirements: Optional[List[str]] = None,
                         timeout: float = 30.0) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())

        task_request = TaskRequest(
            task_id=task_id,
            task_description=task_description,
            task_type=task_type,
            requirements=requirements,
            timeout=timeout
        )

        task_state = TaskState(task_id, task_request)
        self.tasks[task_id] = task_state

        task_msg = self.server.create_message(
            MessageType.TASK_REQUEST,
            task_request.model_dump()
        )

        eligible_nodes = self._get_eligible_nodes(task_request)
        if not eligible_nodes:
            return {'error': 'No eligible nodes available'}

        print(f"Submitting task {task_id} to {len(eligible_nodes)} nodes")

        for node_id in eligible_nodes:
            await self.server.send_to_node(node_id, task_msg)

        while not task_state.completed:
            await asyncio.sleep(0.1)

        return task_state.result or {'error': 'Task failed'}

    async def start_discussion(self, topic: str, participant_ids: Optional[List[str]] = None,
                               max_rounds: int = 3) -> Dict[str, Any]:
        discussion_id = str(uuid.uuid4())

        if participant_ids:
            participants = set(participant_ids)
        else:
            participants = set(self.connected_nodes.keys())

        disc_state = DiscussionState(discussion_id, topic, participants)
        self.discussions[discussion_id] = disc_state

        initial_msg = DiscussionMessage(
            discussion_id=discussion_id,
            message_index=0,
            content=f"Let's discuss: {topic}",
            agreement=1.0
        )

        discussion_msg = self.server.create_message(
            MessageType.DISCUSSION_MESSAGE,
            initial_msg.model_dump()
        )

        for node_id in participants:
            await self.server.send_to_node(node_id, discussion_msg)

        print(f"Started discussion {discussion_id} on: {topic}")

        await asyncio.sleep(max_rounds * 2)

        summary = self._summarize_discussion(disc_state)
        disc_state.summary = summary

        return {
            'discussion_id': discussion_id,
            'topic': topic,
            'messages_count': len(disc_state.messages),
            'summary': summary
        }

    def _summarize_discussion(self, disc_state: DiscussionState) -> str:
        if not disc_state.messages:
            return "No messages in discussion"

        messages = disc_state.messages
        avg_agreement = sum(
            m.get('agreement', 0) for m in messages
        ) / len(messages)

        return f"Discussion completed. {len(messages)} messages. Average agreement: {avg_agreement:.2f}"

    def get_node_info(self, node_id: Optional[str] = None) -> Any:
        if node_id:
            return self.connected_nodes.get(node_id)
        return list(self.connected_nodes.values())

    async def start(self):
        print(f"Starting Coordinator on {self.server.host}:{self.server.port}")
        await self.server.start()

    async def stop(self):
        await self.server.stop()
