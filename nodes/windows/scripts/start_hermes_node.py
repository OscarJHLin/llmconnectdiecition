#!/usr/bin/env python3
import asyncio
import argparse
import yaml
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from nodes.common.compute.hermes_node import HermesComputeNode

def main():
    parser = argparse.ArgumentParser(description="Start the Hermes-based Compute Node")
    default_config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "hermes_node.yaml")
    parser.add_argument("--config", "-c", default=default_config, help="Path to config file")
    parser.add_argument("--name", help="Node name")
    parser.add_argument("--capabilities", nargs="+", help="Capabilities (inference, embedding, analysis, tool_calling)")
    args = parser.parse_args()

    config = {}
    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    
    node_name = args.name or config.get('node', {}).get('name', None)
    
    capabilities = args.capabilities or config.get('node', {}).get('capabilities', ["inference", "embedding", "analysis", "tool_calling"])

    node = HermesComputeNode(
        node_name=node_name,
        capabilities=capabilities
    )

    print(f"Starting Hermes Compute Node: {node.node_name}")
    print(f"Platform: {node.platform.value}")
    print(f"Capabilities: {capabilities}")

    try:
        asyncio.run(node.start())
    except KeyboardInterrupt:
        print("\nShutting down...")
        asyncio.run(node.stop())

if __name__ == "__main__":
    main()