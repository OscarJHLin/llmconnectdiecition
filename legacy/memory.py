import os
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

import chromadb
from chromadb.utils import embedding_functions


class MemoryItem:
    def __init__(self, content: str, metadata: Optional[Dict[str, Any]] = None):
        self.id = str(uuid.uuid4())
        self.content = content
        self.metadata = metadata or {}
        self.created_at = datetime.now().isoformat()
        self.access_count = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'content': self.content,
            'metadata': self.metadata,
            'created_at': self.created_at,
            'access_count': self.access_count
        }


class MemoryManager:
    def __init__(self, db_path: str, collection_name: str = "ai_memory"):
        self.db_path = db_path
        self.collection_name = collection_name
        os.makedirs(db_path, exist_ok=True)

        self.client = chromadb.PersistentClient(path=db_path)
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function
        )

    def add_memory(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        memory_id = str(uuid.uuid4())
        metadata = metadata or {}
        metadata['created_at'] = datetime.now().isoformat()
        metadata['access_count'] = 0

        self.collection.add(
            documents=[content],
            metadatas=[metadata],
            ids=[memory_id]
        )
        return memory_id

    def search_memories(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )

        memories = []
        if results['documents'] and results['documents'][0]:
            for doc, meta, dist in zip(
                results['documents'][0],
                results['metadatas'][0],
                results['distances'][0]
            ):
                memories.append({
                    'content': doc,
                    'metadata': meta,
                    'distance': dist
                })

        return memories

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        result = self.collection.get(ids=[memory_id])
        if result['documents']:
            return {
                'content': result['documents'][0],
                'metadata': result['metadatas'][0]
            }
        return None

    def update_memory(self, memory_id: str, content: Optional[str] = None,
                     metadata: Optional[Dict[str, Any]] = None):
        current = self.get_memory(memory_id)
        if current:
            new_content = content or current['content']
            new_meta = metadata or current['metadata']
            if 'access_count' in new_meta:
                new_meta['access_count'] += 1
            self.collection.update(
                ids=[memory_id],
                documents=[new_content],
                metadatas=[new_meta]
            )

    def delete_memory(self, memory_id: str):
        self.collection.delete(ids=[memory_id])

    def list_memories(self, limit: int = 100) -> List[Dict[str, Any]]:
        result = self.collection.get()
        memories = []
        if result['documents']:
            for doc, meta, mid in zip(
                result['documents'],
                result['metadatas'],
                result['ids']
            ):
                memories.append({
                    'id': mid,
                    'content': doc,
                    'metadata': meta
                })
        return memories[:limit]


class ConversationHistory:
    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.max_messages = 1000

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        self.messages.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {}
        })
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def get_recent_messages(self, count: int = 10) -> List[Dict[str, Any]]:
        return self.messages[-count:]

    def search_conversations(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for msg in reversed(self.messages):
            if query_lower in msg['content'].lower():
                results.append(msg)
                if len(results) >= top_k:
                    break
        return results
