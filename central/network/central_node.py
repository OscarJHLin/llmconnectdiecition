import asyncio
import json
import socket
import struct
import uuid
from typing import Dict, List, Optional, Set, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

class NodeType(Enum):
    COMPUTE_CENTER = "compute_center"
    COMPUTE_NODE = "compute_node"
    NETWORK_ROUTER = "network_router"

class NodeStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    IDLE = "idle"

@dataclass
class NetworkNode:
    node_id: str
    node_name: str
    node_type: NodeType
    ip_address: str
    port: int
    status: NodeStatus
    capabilities: List[str]
    last_heartbeat: float
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class CentralNetworkNode:
    def __init__(self, host: str = "0.0.0.0", port: int = 8888, multicast_group: str = "224.0.0.1", multicast_port: int = 5000):
        self.node_id = str(uuid.uuid4())
        self.host = host
        self.port = port
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.connected_nodes: Dict[str, NetworkNode] = {}
        self.message_handlers: Dict[str, callable] = {}
        self._running = False
        self._server = None
        self._multicast_listener = None
        self._heartbeat_task = None
        self._node_timeout = 30
        self.register_handler("DISCOVER", self._handle_discover)
        self.register_handler("REGISTER", self._handle_register)
        self.register_handler("HEARTBEAT", self._handle_heartbeat)
        self.register_handler("MESSAGE", self._handle_message)
        self.register_handler("QUERY_NODES", self._handle_query_nodes)

    def register_handler(self, message_type: str, handler: callable):
        self.message_handlers[message_type] = handler

    async def _handle_discover(self, data: Dict, addr: tuple):
        response = {
            "type": "DISCOVER_RESPONSE",
            "router_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "timestamp": datetime.now().isoformat()
        }
        await self._send_unicast(addr[0], self.port, response)

    async def _handle_register(self, data: Dict, addr: tuple):
        node_id = data.get("node_id")
        if not node_id:
            node_id = str(uuid.uuid4())
        
        new_node = NetworkNode(
            node_id=node_id,
            node_name=data.get("node_name", "unknown"),
            node_type=NodeType(data.get("node_type", "compute_node")),
            ip_address=addr[0],
            port=data.get("port", 0),
            status=NodeStatus.ONLINE,
            capabilities=data.get("capabilities", []),
            last_heartbeat=datetime.now().timestamp(),
            metadata=data.get("metadata", {})
        )
        
        self.connected_nodes[node_id] = new_node
        print(f"Node registered: {new_node.node_name} ({new_node.node_type.value}) at {addr[0]}")
        
        response = {
            "type": "REGISTER_RESPONSE",
            "success": True,
            "node_id": node_id,
            "message": "Registration successful"
        }
        await self._send_unicast(addr[0], self.port, response, expect_response=False)

    async def _handle_heartbeat(self, data: Dict, addr: tuple):
        node_id = data.get("node_id")
        if node_id in self.connected_nodes:
            self.connected_nodes[node_id].last_heartbeat = datetime.now().timestamp()
            self.connected_nodes[node_id].status = NodeStatus(data.get("status", "online"))
            if "capabilities" in data:
                self.connected_nodes[node_id].capabilities = data["capabilities"]

    async def _handle_message(self, data: Dict, addr: tuple):
        target_id = data.get("target_id")
        if target_id and target_id in self.connected_nodes:
            target_node = self.connected_nodes[target_id]
            forward_data = {
                "type": "FORWARDED_MESSAGE",
                "source_id": data.get("node_id"),
                "content": data.get("content"),
                "timestamp": datetime.now().isoformat()
            }
            await self._send_unicast(target_node.ip_address, self.port, forward_data)

    async def _handle_query_nodes(self, data: Dict, addr: tuple):
        nodes_info = []
        for node_id, node in self.connected_nodes.items():
            nodes_info.append({
                "node_id": node_id,
                "node_name": node.node_name,
                "node_type": node.node_type.value,
                "ip_address": node.ip_address,
                "status": node.status.value,
                "capabilities": node.capabilities
            })
        
        response = {
            "type": "NODES_LIST",
            "nodes": nodes_info,
            "total": len(nodes_info)
        }
        await self._send_unicast(addr[0], self.port, response)

    async def _send_message_with_length(self, writer: asyncio.StreamWriter, data: Dict):
        """Send message with length prefix to handle variable-length messages."""
        message = json.dumps(data).encode('utf-8')
        length = len(message)
        writer.write(struct.pack('!I', length))
        writer.write(message)
        await writer.drain()

    async def _read_message_with_length(self, reader: asyncio.StreamReader) -> Optional[Dict]:
        """Read message with length prefix."""
        try:
            length_data = await reader.readexactly(4)
            length = struct.unpack('!I', length_data)[0]
            message_data = await reader.readexactly(length)
            return json.loads(message_data.decode('utf-8'))
        except (asyncio.IncompleteReadError, ConnectionResetError, json.JSONDecodeError):
            return None

    async def _send_unicast(self, ip: str, port: int, data: Dict, expect_response: bool = False):
        try:
            reader, writer = await asyncio.open_connection(ip, port)
            await self._send_message_with_length(writer, data)

            if expect_response:
                response = await self._read_message_with_length(reader)
                if response:
                    return response

            writer.close()
            await writer.wait_closed()
            return None
        except Exception as e:
            print(f"Failed to send to {ip}:{port}: {e}")
            return None

    async def _send_multicast(self, data: Dict):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        message = json.dumps(data).encode()
        sock.sendto(message, (self.multicast_group, self.multicast_port))
        sock.close()

    async def _multicast_listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', self.multicast_port))
        
        mreq = socket.inet_aton(self.multicast_group) + socket.inet_aton('0.0.0.0')
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        while self._running:
            try:
                data, addr = await asyncio.get_event_loop().sock_recvfrom(sock, 1024)
                message = json.loads(data.decode())
                message_type = message.get("type")
                if message_type in self.message_handlers:
                    await self.message_handlers[message_type](message, addr)
            except Exception as e:
                print(f"Error parsing multicast message: {e}")

    async def _tcp_server(self):
        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            addr = writer.get_extra_info('peername')
            try:
                message = await self._read_message_with_length(reader)
                if message:
                    message_type = message.get("type")
                    if message_type in self.message_handlers:
                        await self.message_handlers[message_type](message, addr)
                        
                        response = {"type": "ACK", "status": "ok"}
                        await self._send_message_with_length(writer, response)
            except Exception as e:
                print(f"Error handling client {addr}: {e}")
            finally:
                writer.close()
                await writer.wait_closed()
        
        self._server = await asyncio.start_server(handle_client, self.host, self.port)
        async with self._server:
            await self._server.serve_forever()

    async def _heartbeat_check(self):
        while self._running:
            current_time = datetime.now().timestamp()
            to_remove = []
            for node_id, node in self.connected_nodes.items():
                if current_time - node.last_heartbeat > self._node_timeout:
                    node.status = NodeStatus.OFFLINE
                    print(f"Node {node.node_name} timed out")
                    to_remove.append(node_id)
            
            for node_id in to_remove:
                del self.connected_nodes[node_id]
            
            await asyncio.sleep(5)

    async def broadcast_message(self, message: Dict, exclude_nodes: Optional[Set[str]] = None):
        exclude_nodes = exclude_nodes or set()
        for node_id, node in self.connected_nodes.items():
            if node_id not in exclude_nodes and node.status == NodeStatus.ONLINE:
                await self._send_unicast(node.ip_address, self.port, message)

    async def send_to_node(self, node_id: str, message: Dict):
        if node_id in self.connected_nodes:
            node = self.connected_nodes[node_id]
            if node.status == NodeStatus.ONLINE:
                await self._send_unicast(node.ip_address, self.port, message)

    def get_nodes_by_type(self, node_type: NodeType) -> List[NetworkNode]:
        return [node for node in self.connected_nodes.values() if node.node_type == node_type]

    def get_node_status(self, node_id: str) -> Optional[NodeStatus]:
        node = self.connected_nodes.get(node_id)
        if node:
            return node.status
        return None

    async def start(self):
        self._running = True
        print(f"Starting Central Network Node at {self.host}:{self.port}")
        print(f"Multicast discovery: {self.multicast_group}:{self.multicast_port}")
        
        tasks = [
            asyncio.create_task(self._tcp_server()),
            asyncio.create_task(self._multicast_listener()),
            asyncio.create_task(self._heartbeat_check())
        ]
        
        await asyncio.gather(*tasks)

    async def stop(self):
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        print("Central Network Node stopped")