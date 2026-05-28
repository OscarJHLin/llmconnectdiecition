import asyncio
import json
import socket
import struct
import uuid
import platform
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from enum import Enum

class OSPlatform(Enum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    ANDROID = "android"
    IOS = "ios"
    UNKNOWN = "unknown"

def get_platform() -> OSPlatform:
    system = platform.system().lower()
    if system == "windows":
        return OSPlatform.WINDOWS
    elif system == "darwin":
        return OSPlatform.MACOS
    elif system == "linux":
        try:
            with open("/proc/version", "r") as f:
                if "android" in f.read().lower():
                    return OSPlatform.ANDROID
        except:
            pass
        return OSPlatform.LINUX
    else:
        return OSPlatform.UNKNOWN

class NetworkClient:
    def __init__(self, node_name: str = None, node_type: str = "compute_node", capabilities: Optional[List[str]] = None):
        self.node_id = str(uuid.uuid4())
        self.node_name = node_name or f"node_{self.node_id[:8]}"
        self.node_type = node_type
        self.capabilities = capabilities or []
        self.platform = get_platform()
        self.router_host = None
        self.router_port = None
        self._running = False
        self._connection_task = None
        self._heartbeat_task = None
        self._message_handler = None
        self._on_connected = None
        self._on_disconnected = None
        self._on_message = None
        self._multicast_group = "224.0.0.1"
        self._multicast_port = 5000
        self._heartbeat_interval = 10

    def set_message_handler(self, handler: Callable[[Dict], None]):
        self._message_handler = handler

    def set_connection_callbacks(self, on_connected=None, on_disconnected=None, on_message=None):
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_message = on_message

    async def _discover_router(self) -> Optional[tuple]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(5)
        
        discover_msg = json.dumps({
            "type": "DISCOVER",
            "node_id": self.node_id,
            "timestamp": datetime.now().isoformat()
        }).encode()
        
        for _ in range(3):
            try:
                sock.sendto(discover_msg, (self._multicast_group, self._multicast_port))
                data, addr = sock.recvfrom(1024)
                response = json.loads(data.decode())
                if response.get("type") == "DISCOVER_RESPONSE":
                    sock.close()
                    return (response["host"], response["port"])
            except socket.timeout:
                continue
        
        sock.close()
        return None

    async def _send_message_with_length(self, writer: asyncio.StreamWriter, data: Dict):
        """Send message with length prefix."""
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

    async def _send_to_router(self, message: Dict):
        if not self.router_host or not self.router_port:
            return False
        
        try:
            reader, writer = await asyncio.open_connection(self.router_host, self.router_port)
            await self._send_message_with_length(writer, message)
            
            response_data = await self._read_message_with_length(reader)
            if response_data:
                if self._message_handler:
                    if asyncio.iscoroutinefunction(self._message_handler):
                        await self._message_handler(response_data)
                    else:
                        self._message_handler(response_data)

            writer.close()
            await writer.wait_closed()
            return True
        except Exception as e:
            print(f"Failed to send to router: {e}")
            return False

    async def _register_with_router(self):
        registration = {
            "type": "REGISTER",
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "platform": self.platform.value,
            "capabilities": self.capabilities,
            "metadata": {
                "os": self.platform.value,
                "python_version": platform.python_version(),
                "hostname": platform.node()
            },
            "timestamp": datetime.now().isoformat()
        }
        return await self._send_to_router(registration)

    async def _send_heartbeat(self):
        while self._running:
            if self.router_host and self.router_port:
                heartbeat = {
                    "type": "HEARTBEAT",
                    "node_id": self.node_id,
                    "status": "online",
                    "capabilities": self.capabilities,
                    "timestamp": datetime.now().isoformat()
                }
                await self._send_to_router(heartbeat)
            await asyncio.sleep(self._heartbeat_interval)

    async def _connect_loop(self):
        while self._running:
            if not self.router_host or not self.router_port:
                print("Discovering router...")
                result = await self._discover_router()
                if result:
                    self.router_host, self.router_port = result
                    print(f"Found router at {self.router_host}:{self.router_port}")
                    
                    registered = await self._register_with_router()
                    if registered:
                        print(f"Successfully registered as {self.node_name}")
                        if self._on_connected:
                            if asyncio.iscoroutinefunction(self._on_connected):
                                await self._on_connected(self.router_host, self.router_port)
                            else:
                                self._on_connected(self.router_host, self.router_port)
                else:
                    print("Router not found, retrying...")
                    await asyncio.sleep(3)
                    continue
            
            await asyncio.sleep(1)

    async def send_message(self, content: Any, target_id: Optional[str] = None):
        message = {
            "type": "MESSAGE",
            "node_id": self.node_id,
            "content": content,
            "target_id": target_id,
            "timestamp": datetime.now().isoformat()
        }
        return await self._send_to_router(message)

    async def query_nodes(self) -> Optional[Dict]:
        message = {
            "type": "QUERY_NODES",
            "node_id": self.node_id,
            "timestamp": datetime.now().isoformat()
        }
        
        if not self.router_host or not self.router_port:
            return None
        
        try:
            reader, writer = await asyncio.open_connection(self.router_host, self.router_port)
            await self._send_message_with_length(writer, message)
            
            response_data = await self._read_message_with_length(reader)
            writer.close()
            await writer.wait_closed()
            
            if response_data:
                return response_data
        except Exception as e:
            print(f"Failed to query nodes: {e}")
        
        return None

    def update_capabilities(self, capabilities: List[str]):
        self.capabilities = capabilities

    async def start(self):
        self._running = True
        print(f"Starting network client: {self.node_name} ({self.platform.value})")
        
        tasks = [
            asyncio.create_task(self._connect_loop()),
            asyncio.create_task(self._send_heartbeat())
        ]
        
        await asyncio.gather(*tasks)

    async def stop(self):
        self._running = False
        if self._on_disconnected:
            self._on_disconnected()
        print("Network client stopped")

    def get_info(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "platform": self.platform.value,
            "capabilities": self.capabilities,
            "router_host": self.router_host,
            "router_port": self.router_port,
            "connected": self.router_host is not None
        }
