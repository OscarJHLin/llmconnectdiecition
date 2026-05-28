import asyncio
import json
import time
import uuid
from typing import Dict, Optional, Callable, Set
import websockets
from websockets.server import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed

from .protocol import BaseMessage, MessageType, NodeInfo


class MessageHandler:
    def __init__(self):
        self.handlers: Dict[MessageType, Callable] = {}

    def register_handler(self, message_type: MessageType, handler: Callable):
        self.handlers[message_type] = handler

    async def handle_message(self, message: BaseMessage, **kwargs):
        handler = self.handlers.get(message.message_type)
        if handler:
            return await handler(message, **kwargs)
        return None


class WebSocketNode:
    def __init__(self, node_id: str, node_info: Optional[NodeInfo] = None):
        self.node_id = node_id
        self.node_info = node_info
        self.websocket: Optional[WebSocketServerProtocol] = None
        self.message_handler = MessageHandler()
        self._running = False
        self._message_queue = asyncio.Queue()
        self._connected_nodes: Set[str] = set()

    def generate_message_id(self) -> str:
        return str(uuid.uuid4())

    def create_message(self, message_type: MessageType, payload: dict) -> BaseMessage:
        return BaseMessage(
            message_id=self.generate_message_id(),
            message_type=message_type,
            sender_id=self.node_id,
            timestamp=time.time(),
            payload=payload
        )

    async def send_message(self, message: BaseMessage):
        if self.websocket:
            try:
                msg_dict = message.model_dump()
                msg_dict['message_type'] = message.message_type.value
                await self.websocket.send(json.dumps(msg_dict))
            except Exception as e:
                print(f"Failed to send message: {e}")

    async def receive_message(self) -> Optional[BaseMessage]:
        try:
            if self.websocket:
                data = await self.websocket.recv()
                msg_dict = json.loads(data)
                msg_dict['message_type'] = MessageType(msg_dict['message_type'])
                return BaseMessage(**msg_dict)
        except Exception as e:
            print(f"Failed to receive message: {e}")
        return None

    async def start(self):
        raise NotImplementedError

    async def stop(self):
        self._running = False


class WebSocketServer(WebSocketNode):
    def __init__(self, host: str, port: int, node_info: NodeInfo):
        super().__init__(node_info.node_id, node_info)
        self.host = host
        self.port = port
        self._clients: Dict[str, WebSocketServerProtocol] = {}
        self._client_infos: Dict[str, NodeInfo] = {}

    async def handle_client(self, websocket: WebSocketServerProtocol, path: str):
        client_id = None
        try:
            async for message in websocket:
                try:
                    msg_dict = json.loads(message)
                    msg_dict['message_type'] = MessageType(msg_dict['message_type'])
                    base_msg = BaseMessage(**msg_dict)

                    if base_msg.message_type == MessageType.HELLO:
                        client_id = base_msg.sender_id
                        self._clients[client_id] = websocket
                        self._client_infos[client_id] = NodeInfo(**base_msg.payload['node_info'])
                        self._connected_nodes.add(client_id)
                        print(f"Node {client_id} connected")

                    await self.message_handler.handle_message(
                        base_msg,
                        websocket=websocket,
                        client_id=client_id
                    )
                except Exception as e:
                    print(f"Error handling message: {e}")
        except ConnectionClosed:
            print(f"Connection with {client_id} closed")
        finally:
            if client_id:
                if client_id in self._clients:
                    del self._clients[client_id]
                if client_id in self._client_infos:
                    del self._client_infos[client_id]
                self._connected_nodes.discard(client_id)

    async def broadcast(self, message: BaseMessage, exclude: Optional[Set[str]] = None):
        exclude = exclude or set()
        tasks = []
        for client_id, websocket in self._clients.items():
            if client_id not in exclude:
                tasks.append(self._send_to_client(websocket, message))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def send_to_node(self, node_id: str, message: BaseMessage):
        if node_id in self._clients:
            await self._send_to_client(self._clients[node_id], message)

    async def _send_to_client(self, websocket: WebSocketServerProtocol, message: BaseMessage):
        try:
            msg_dict = message.model_dump()
            msg_dict['message_type'] = message.message_type.value
            await websocket.send(json.dumps(msg_dict))
        except Exception as e:
            print(f"Failed to send to client: {e}")

    async def start(self):
        self._running = True
        self.server = await websockets.serve(
            self.handle_client,
            self.host, self.port
        )
        print(f"WebSocket server started on {self.host}:{self.port}")
        await asyncio.Future()

    async def stop(self):
        self._running = False
        self.server.close()
        await self.server.wait_closed()


class WebSocketClient(WebSocketNode):
    def __init__(self, node_info: NodeInfo, server_uri: str):
        super().__init__(node_info.node_id, node_info)
        self.server_uri = server_uri
        self._reconnect_interval = 5

    async def connect(self):
        while self._running:
            try:
                self.websocket = await websockets.connect(self.server_uri)
                print(f"Connected to {self.server_uri}")

                hello_msg = self.create_message(
                    MessageType.HELLO,
                    {'node_info': self.node_info.model_dump()}
                )
                await self.send_message(hello_msg)

                await self._message_loop()
            except Exception as e:
                    print(f"Connection error: {e}")
                    await asyncio.sleep(self._reconnect_interval)

    async def _message_loop(self):
        while self._running and self.websocket:
            try:
                message = await self.receive_message()
                if message:
                    await self.message_handler.handle_message(message)
            except ConnectionClosed:
                    print("Server disconnected")
                    break
            except Exception as e:
                print(f"Error in message loop: {e}")

    async def start(self):
        self._running = True
        await self.connect()

    async def stop(self):
        self._running = False
        if self.websocket:
            await self.websocket.close()
