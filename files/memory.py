from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.config import Settings


# Below this, a stored memory/document isn't about the question (measured with Chroma's
# default embedding model: related questions score ~0.5-0.7, unrelated ones <= 0.2)
MIN_RELEVANCE = 0.35


def similarity(distance, space):
    """Turn a Chroma distance into a 0-1 similarity (embeddings are normalized)."""
    return 1 - distance / 2 if space == "l2" else 1 - distance


def relevant_documents(collection, query, top_k, min_similarity):
    """Query a collection and keep only results at least `min_similarity` similar."""
    count = collection.count()
    if count == 0:
        return []
    results = collection.query(query_texts=[query], n_results=min(top_k, count))
    space = (collection.metadata or {}).get("hnsw:space", "l2")
    return [doc for doc, distance in zip(results['documents'][0], results['distances'][0])
            if min_similarity is None or similarity(distance, space) >= min_similarity]


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

    def get_context_from_search(self, query: str, top_k: int = 3, min_similarity=MIN_RELEVANCE) -> str:
        """Search memory for earlier conversations about the same thing.

        Args:
            query (str): Search query
            top_k (int): Number of results to return
            min_similarity (float): Skip memories less similar than this (None keeps all)

        Returns:
            str: Formatted context from search results, or "" if nothing relevant
        """
        try:
            docs = relevant_documents(self.collection, query, top_k, min_similarity)
            if not docs:
                return ""
            return "Related memory (from earlier conversations; may be out of date):\n" + "".join(
                f"{i}. {doc[:300]}{'...' if len(doc) > 300 else ''}\n" for i, doc in enumerate(docs, 1)
            )
        except Exception as e:
            print(f"Error searching memory: {e}")
            return ""
