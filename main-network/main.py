#!/usr/bin/env python3
"""
NetConnect Main Network Node - 主网络节点
仅命令行运行，无需Web UI
负责节点发现、消息路由、心跳管理
运行方式: python main.py [--port 8888]
"""

import sys
import os
import socket
import json
import asyncio
import struct
import argparse
from datetime import datetime

def log(message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")

async def handle_client(reader, writer, connected_nodes, multicast_group, multicast_port):
    addr = writer.get_extra_info("peername")
    log(f"New connection from {addr}")
    try:
        while True:
            length_data = await reader.readexactly(4)
            length = struct.unpack('!I', length_data)[0]
            data = await reader.readexactly(length)
            message = json.loads(data.decode('utf-8'))
            msg_type = message.get("type")

            if msg_type == "REGISTER":
                node_id = f"node_{len(connected_nodes) + 1}"
                connected_nodes[node_id] = {
                    "node_name": message.get("node_name", "Unknown"),
                    "node_type": message.get("node_type", "COMPUTE"),
                    "capabilities": message.get("capabilities", []),
                    "ip_address": addr[0],
                    "status": "online",
                    "last_heartbeat": datetime.now().isoformat(),
                }
                response = {"type": "REGISTER_RESPONSE", "status": "OK", "node_id": node_id}
                send_message(writer, response)
                log(f"✓ Node registered: {connected_nodes[node_id]['node_name']} ({addr[0]})")
                log(f"  Capabilities: {', '.join(connected_nodes[node_id]['capabilities'])}")
                log(f"  Total connected nodes: {len(connected_nodes)}")

            elif msg_type == "HEARTBEAT":
                for nid, node in connected_nodes.items():
                    if node["ip_address"] == addr[0]:
                        node["status"] = "online"
                        node["last_heartbeat"] = datetime.now().isoformat()
                        break

            elif msg_type == "TASK_RESULT":
                task_id = message.get("task_id")
                log(f"✓ Task result received: {task_id[:8]}... from {addr[0]}")

            elif msg_type == "STATUS_REQUEST":
                response = {"type": "STATUS_RESPONSE", "nodes": list(connected_nodes.values())}
                send_message(writer, response)

    except Exception as e:
        for nid, node in list(connected_nodes.items()):
            if node["ip_address"] == addr[0]:
                log(f"✗ Node disconnected: {node['node_name']}")
                del connected_nodes[nid]
                log(f"  Total connected nodes: {len(connected_nodes)}")
                break
        writer.close()

def send_message(writer, data):
    message = json.dumps(data).encode('utf-8')
    writer.write(struct.pack('!I', len(message)))
    writer.write(message)

async def discovery_server(multicast_group, multicast_port, tcp_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', multicast_port))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                    socket.inet_aton(multicast_group) + socket.inet_aton('0.0.0.0'))
    log(f"Multicast discovery listening on {multicast_group}:{multicast_port}")
    while True:
        data, addr = sock.recvfrom(1024)
        try:
            msg = json.loads(data.decode('utf-8'))
            if msg.get("type") == "DISCOVER":
                response = {"type": "DISCOVER_RESPONSE", "port": tcp_port}
                sock.sendto(json.dumps(response).encode('utf-8'), addr)
                log(f"→ Discovery request from {addr[0]}")
        except:
            pass

async def heartbeat_checker(connected_nodes, timeout=30):
    """定期检查节点心跳，超时则标记为离线"""
    while True:
        await asyncio.sleep(5)
        now = datetime.now()
        for nid, node in list(connected_nodes.items()):
            last = datetime.fromisoformat(node.get("last_heartbeat", "2000-01-01T00:00:00"))
            if (now - last).total_seconds() > timeout:
                if node["status"] == "online":
                    node["status"] = "offline"
                    log(f"⚠ Node timeout: {node['node_name']} ({node['ip_address']})")

async def main(port, multicast_group, multicast_port):
    connected_nodes = {}
    
    print("=" * 60)
    print("  NetConnect Main Network Router")
    print("=" * 60)
    print(f"  TCP Port: {port}")
    print(f"  Multicast: {multicast_group}:{multicast_port}")
    print("=" * 60)
    log("Starting main network router...")

    asyncio.create_task(discovery_server(multicast_group, multicast_port, port))
    asyncio.create_task(heartbeat_checker(connected_nodes))
    
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, connected_nodes, multicast_group, multicast_port),
        '0.0.0.0', port
    )
    
    log(f"TCP server listening on 0.0.0.0:{port}")
    log("Ready to accept connections...")
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NetConnect Main Network Router")
    parser.add_argument("--port", type=int, default=8888, help="TCP port for node connections")
    parser.add_argument("--multicast-group", type=str, default="224.0.0.1", help="Multicast group address")
    parser.add_argument("--multicast-port", type=int, default=5000, help="Multicast port")
    args = parser.parse_args()
    
    try:
        asyncio.run(main(args.port, args.multicast_group, args.multicast_port))
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("  Shutting down...")
        print("=" * 60)
