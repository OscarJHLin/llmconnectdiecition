#!/usr/bin/env python3
import asyncio
import argparse
import yaml
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from central.compute.central_compute import CentralComputeNode, TaskType
from central.ai.model_adapter import ModelBackend

def main():
    parser = argparse.ArgumentParser(description="Start the Central Compute Node")
    default_config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "central_compute.yaml")
    parser.add_argument("--config", "-c", default=default_config, help="Path to config file")
    parser.add_argument("--name", help="Node name")
    parser.add_argument("--backend", choices=["ollama", "vllm", "lm_studio", "openai"], help="AI backend")
    parser.add_argument("--port", type=int, help="AI backend port")
    args = parser.parse_args()

    config = {}
    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    
    node_name = args.name or config.get('node', {}).get('name', 'central_compute')
    
    backend_str = args.backend or config.get('ai', {}).get('backend', 'ollama')
    backend = ModelBackend[backend_str.upper()]
    
    ai_port = args.port or config.get('ai', {}).get('port', 11434)

    node = CentralComputeNode(
        node_name=node_name,
        ai_backend=backend,
        ai_port=ai_port
    )

    print(f"Starting Central Compute Node: {node_name}")
    print(f"AI Backend: {backend.value} (port {ai_port})")

    async def run_with_demo():
        task = asyncio.create_task(node.start())
        
        await asyncio.sleep(5)
        
        print("\n=== Testing local inference ===")
        result = await node.run_local_inference("Hello! What is your name?")
        print(f"AI Response: {result}")
        
        await task

    try:
        asyncio.run(run_with_demo())
    except KeyboardInterrupt:
        print("\nShutting down...")
        asyncio.run(node.stop())

if __name__ == "__main__":
    main()