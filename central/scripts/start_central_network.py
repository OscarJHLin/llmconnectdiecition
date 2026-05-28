#!/usr/bin/env python3
import asyncio
import argparse
import yaml
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from central.network.central_node import CentralNetworkNode

def main():
    parser = argparse.ArgumentParser(description="Start the Central Network Node")
    default_config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "central_network.yaml")
    parser.add_argument("--config", "-c", default=default_config, help="Path to config file")
    parser.add_argument("--host", help="Host address")
    parser.add_argument("--port", type=int, help="Port number")
    args = parser.parse_args()

    config = {}
    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    
    host = args.host or config.get('network', {}).get('host', '0.0.0.0')
    port = args.port or config.get('network', {}).get('port', 8888)
    multicast_group = config.get('network', {}).get('multicast_group', '224.0.0.1')
    multicast_port = config.get('network', {}).get('multicast_port', 5000)

    node = CentralNetworkNode(
        host=host,
        port=port,
        multicast_group=multicast_group,
        multicast_port=multicast_port
    )

    print(f"Starting Central Network Node at {host}:{port}")
    print(f"Multicast: {multicast_group}:{multicast_port}")

    try:
        asyncio.run(node.start())
    except KeyboardInterrupt:
        print("\nShutting down...")
        asyncio.run(node.stop())

if __name__ == "__main__":
    main()