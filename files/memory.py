from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.config import Settings


@lru_cache(maxsize=None)
def get_chroma_client(db_path):
    """Return one shared persistent ChromaDB client per storage folder."""
    Path(db_path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(db_path),
        settings=Settings(anonymized_telemetry=False)
    )


class Memory:
    """Vector memory system using ChromaDB for semantic search."""

    def __init__(self, db_path="./data/chroma"):
        """Initialize ChromaDB connection.

        Args:
            db_path (str): Path to ChromaDB storage
        """
        self.db_path = str(db_path)
        self.client = get_chroma_client(self.db_path)
        self.collection = self._get_collection()

    def _get_collection(self):
        return self.client.get_or_create_collection(
            name="conversations",
            metadata={"hnsw:space": "cosine"}
        )

    def add_conversation(self, user_message: str, assistant_response: str, message_id):
        """Add a conversation to vector memory.

        Args:
            user_message (str): User's message
            assistant_response (str): AI's response
            message_id: Unique message ID
        """
        try:
            self.collection.upsert(
                ids=[str(message_id)],
                documents=[f"{user_message} {assistant_response}"],
                metadatas=[{
                    "user": user_message[:200],
                    "assistant": assistant_response[:200],
                    "type": "conversation"
                }]
            )
        except Exception as e:
            print(f"Error adding to memory: {e}")

    def get_context_from_search(self, query: str, top_k: int = 3) -> str:
        """Search memory for relevant context.

        Args:
            query (str): Search query
            top_k (int): Number of results to return

        Returns:
            str: Formatted context from search results
        """
        try:
            count = self.collection.count()
            if count == 0:
                return ""
            results = self.collection.query(query_texts=[query], n_results=min(top_k, count))
            docs = results['documents'][0] if results['documents'] else []
            if not docs:
                return ""
            return "Related memory:\n" + "".join(
                f"{i}. {doc[:300]}...\n" for i, doc in enumerate(docs, 1)
            )
        except Exception as e:
            print(f"Error searching memory: {e}")
            return ""

    def clear_memory(self):
        """Clear all vector memory."""
        try:
            self.client.delete_collection(name="conversations")
            self.collection = self._get_collection()
        except Exception as e:
            print(f"Error clearing memory: {e}")
