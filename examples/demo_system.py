import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from legacy.coordinator import Coordinator
from legacy.ai_node import AINode


async def run_coordinator():
    coordinator = Coordinator(host="127.0.0.1", port=8000)

    await asyncio.sleep(1)

    task = asyncio.create_task(coordinator.start())

    await asyncio.sleep(2)

    while len(coordinator.connected_nodes) < 3:
        print(f"Waiting for nodes to connect... ({len(coordinator.connected_nodes)}/3)")
        await asyncio.sleep(1)

    print("\n=== All nodes connected! ===")
    print(f"Connected nodes: {[n.node_name for n in coordinator.connected_nodes.values()]}")

    await asyncio.sleep(1)

    print("\n=== Submitting task: 'Solve complex problem' ===")
    result = await coordinator.submit_task(
        "Solve a complex multi-disciplinary problem",
        requirements=["analysis", "reasoning"]
    )
    print(f"Task result: {result}")

    await asyncio.sleep(2)

    print("\n=== Starting discussion: 'What is the best approach?' ===")
    discussion_result = await coordinator.start_discussion(
        "What is the best approach to solve this problem?",
        max_rounds=2
    )
    print(f"Discussion result: {discussion_result}")

    await asyncio.sleep(5)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def run_node(node_name: str, specialty: str):
    node = AINode(
        node_name=node_name,
        specialty=specialty,
        memory_db_path=f"./data/memory_{node_name}",
        coordinator_uri="ws://127.0.0.1:8000",
        capabilities=["analysis", "reasoning"]
    )

    node.add_knowledge(
        f"I am specialized in {specialty}. I have deep expertise in this field.",
        {"type": "identity", "specialty": specialty}
    )

    task = asyncio.create_task(node.start())

    await asyncio.Future()


async def main():
    os.makedirs("./data", exist_ok=True)

    coordinator_task = asyncio.create_task(run_coordinator())

    await asyncio.sleep(1)

    node1_task = asyncio.create_task(run_node("node1", "mathematics"))
    node2_task = asyncio.create_task(run_node("node2", "computer_science"))
    node3_task = asyncio.create_task(run_node("node3", "physics"))

    await asyncio.sleep(20)

    for task in [coordinator_task, node1_task, node2_task, node3_task]:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSystem stopped by user")
