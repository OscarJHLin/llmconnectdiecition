#!/usr/bin/env python3
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from central.network.central_node import CentralNetworkNode
from central.compute.central_compute import CentralComputeNode, TaskType
from nodes.common.compute.edge_compute import EdgeComputeNode
from central.ai.model_adapter import ModelBackend

async def run_network_node():
    node = CentralNetworkNode(host="127.0.0.1", port=8888)
    await node.start()

async def run_central_compute():
    compute = CentralComputeNode(
        node_name="central_compute",
        ai_backend=ModelBackend.OLLAMA,
        ai_port=11434
    )
    
    await asyncio.sleep(2)
    
    task = asyncio.create_task(compute.start())
    
    await asyncio.sleep(5)
    
    print("\n=== Querying network nodes ===")
    nodes = await compute.network_client.query_nodes()
    print(f"Network nodes: {nodes}")
    
    await asyncio.sleep(3)
    
    print("\n=== Submitting test task ===")
    task_id = await compute.submit_task(
        TaskType.INFERENCE,
        "Explain the theory of relativity in simple terms",
        {"prompt": "Explain the theory of relativity in simple terms"}
    )
    print(f"Task submitted with ID: {task_id}")
    
    await asyncio.sleep(10)
    
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

async def run_edge_node(node_name: str, specialty: str):
    edge = EdgeComputeNode(
        node_name=node_name,
        ai_backend=ModelBackend.OLLAMA,
        ai_port=11434,
        capabilities=["inference", "embedding"]
    )
    
    await edge.start()

async def main():
    print("=== Starting Full System Demo ===")
    print("Creating data directory...")
    os.makedirs("./data", exist_ok=True)
    
    print("\n1. Starting Network Router...")
    network_task = asyncio.create_task(run_network_node())
    
    await asyncio.sleep(2)
    
    print("\n2. Starting Edge Nodes...")
    edge1_task = asyncio.create_task(run_edge_node("edge_mac", "macos"))
    edge2_task = asyncio.create_task(run_edge_node("edge_win", "windows"))
    edge3_task = asyncio.create_task(run_edge_node("edge_linux", "linux"))
    
    await asyncio.sleep(3)
    
    print("\n3. Starting Central Compute Node...")
    compute_task = asyncio.create_task(run_central_compute())
    
    await asyncio.sleep(25)
    
    print("\n=== Stopping System ===")
    for task in [network_task, edge1_task, edge2_task, edge3_task, compute_task]:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    print("\nDemo completed!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSystem stopped by user")