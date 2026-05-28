#!/usr/bin/env python3
"""
Simplified Central Network Node Launcher
Minimal configuration - just run and it works.
"""
import sys
import os
import argparse
import socket
import asyncio

# Add project root to sys.path so we can import central.network.central_node
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from central.network.central_node import CentralNetworkNode


def get_best_interface():
    """Auto-detect the best non-loopback network interface IP."""
    try:
        # Try to connect to a public address to determine the best local interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        # Fallback: try to find any non-loopback interface
        try:
            hostname = socket.gethostname()
            ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
            if ip != "127.0.0.1":
                return ip
        except Exception:
            pass
    return "0.0.0.0"


def print_banner(host, port, node_id):
    """Print a clear status banner."""
    banner = f"""
╔══════════════════════════════════════════════════════════════╗
║           NetConnect Central Network Router                  ║
╠══════════════════════════════════════════════════════════════╣
║  Node ID : {node_id:<46} ║
║  Host    : {host:<46} ║
║  Port    : {port:<46} ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def print_node_joined(node_name, node_type, ip_address, total_nodes):
    """Print a message when a node joins."""
    print(f"[+] Node joined: {node_name} ({node_type}) at {ip_address} | Total nodes: {total_nodes}")


def print_node_left(node_name, total_nodes):
    """Print a message when a node leaves."""
    print(f"[-] Node left:  {node_name} | Total nodes: {total_nodes}")


class SimpleRouterNode(CentralNetworkNode):
    """Extended CentralNetworkNode with simple router logging."""

    async def _handle_register(self, data, addr):
        await super()._handle_register(data, addr)
        node_id = data.get("node_id")
        if node_id and node_id in self.connected_nodes:
            node = self.connected_nodes[node_id]
            print_node_joined(node.node_name, node.node_type.value, node.ip_address, len(self.connected_nodes))

    async def _heartbeat_check(self):
        while self._running:
            current_time = __import__("datetime").datetime.now().timestamp()
            to_remove = []
            for node_id, node in self.connected_nodes.items():
                if current_time - node.last_heartbeat > self._node_timeout:
                    node.status = __import__("central.network.central_node", fromlist=["NodeStatus"]).NodeStatus.OFFLINE
                    print_node_left(node.node_name, len(self.connected_nodes) - 1)
                    to_remove.append(node_id)
            for node_id in to_remove:
                del self.connected_nodes[node_id]
            await asyncio.sleep(5)

    async def start(self):
        self._running = True
        print_banner(self.host, self.port, self.node_id)
        print("Starting TCP server, multicast listener, and heartbeat checker...\n")
        print("Press Ctrl+C to stop.\n")
        tasks = [
            asyncio.create_task(self._tcp_server()),
            asyncio.create_task(self._multicast_listener()),
            asyncio.create_task(self._heartbeat_check()),
        ]
        await asyncio.gather(*tasks)

    async def stop(self):
        print("\n[*] Shutting down Central Network Router...")
        await super().stop()
        print("[*] Router stopped. Goodbye!")


def main():
    parser = argparse.ArgumentParser(description="Start a simplified central network router")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8888, help="Port to listen on (default: 8888)")
    args = parser.parse_args()

    host = args.host
    port = args.port

    # Auto-detect best interface for display purposes
    best_ip = get_best_interface()
    if host == "0.0.0.0":
        print(f"[*] Auto-detected best network interface: {best_ip}")
    else:
        best_ip = host

    node = SimpleRouterNode(host=host, port=port)

    try:
        asyncio.run(node.start())
    except KeyboardInterrupt:
        asyncio.run(node.stop())


if __name__ == "__main__":
    main()
