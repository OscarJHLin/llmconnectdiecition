#!/usr/bin/env python3
import asyncio
import argparse
import yaml
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from nodes.common.compute.edge_compute import EdgeComputeNode
from central.ai.model_adapter import ModelBackend

def main():
    parser = argparse.ArgumentParser(description="Start the Edge Compute Node")
    default_config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "edge_compute.yaml")
    parser.add_argument("--config", "-c", default=default_config, help="Path to config file")
    parser.add_argument("--name", help="Node name")
    parser.add_argument("--backend", choices=["ollama", "vllm", "lm_studio", "openai"], help="AI backend")
    parser.add_argument("--port", type=int, help="AI backend port")
    args = parser.parse_args()

    config = {}
    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    
    node_name = args.name or config.get('node', {}).get('name', None)
    
    backend_str = args.backend or config.get('ai', {}).get('backend', 'ollama')
    backend = ModelBackend[backend_str.upper()]
    
    ai_port = args.port or config.get('ai', {}).get('port', 11434)
    
    capabilities = config.get('node', {}).get('capabilities', ["inference", "embedding"])

    node = EdgeComputeNode(
        node_name=node_name,
        ai_backend=backend,
        ai_port=ai_port,
        capabilities=capabilities
    )

    print(f"Starting Edge Compute Node: {node.node_name}")
    print(f"Platform: {node.platform.value}")
    print(f"AI Backend: {backend.value} (port {ai_port})")

    try:
        asyncio.run(node.start())
    except KeyboardInterrupt:
        print("\nShutting down...")
        asyncio.run(node.stop())

if __name__ == "__main__":
    main()