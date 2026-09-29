from pathlib import Path

import PyPDF2
from docx import Document

from memory import get_chroma_client


class KnowledgeBase:
    """RAG system for document indexing and search."""

    ALLOWED_TYPES = {'.pdf', '.txt', '.docx', '.py', '.js', '.css', '.html',
                     '.json', '.md', '.yaml', '.yml', '.sh'}

    def __init__(self, db_path="./data/chroma"):
        self.client = get_chroma_client(str(db_path))
        self.collection = self.client.get_or_create_collection(name="documents")

    def add_document(self, file_path, doc_name=None):
        """Index a document. Re-adding a document replaces its old chunks.

        Returns:
            tuple: (success, message)
        """
        file_path = Path(file_path)
        doc_name = doc_name or file_path.name
        suffix = file_path.suffix.lower()

        if suffix not in self.ALLOWED_TYPES:
            return False, f"File type '{suffix}' not supported"

        try:
            if suffix == '.pdf':
                text = self._extract_pdf(file_path)
            elif suffix == '.docx':
                text = self._extract_docx(file_path)
            else:
                text = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            return False, f"Could not read document: {e}"

        if not text.strip():
            return False, "Could not extract text"

        chunks = self._chunk_text(text, chunk_size=500, overlap=100)
        try:
            self.collection.delete(where={"source": doc_name})
            self.collection.add(
                ids=[f"{doc_name}_{i}" for i in range(len(chunks))],
                documents=chunks,
                metadatas=[{"source": doc_name}] * len(chunks)
            )
        except Exception as e:
            return False, f"Error indexing document: {e}"

        return True, f"✅ Document '{doc_name}' added ({len(chunks)} chunks)"

    def _extract_pdf(self, file_path):
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            return "\n".join(page.extract_text() or "" for page in reader.pages)

    def _extract_docx(self, file_path):
        doc = Document(str(file_path))
        return "\n".join(para.text for para in doc.paragraphs)

    def _chunk_text(self, text, chunk_size=500, overlap=100):
        step = chunk_size - overlap
        return [text[i:i + chunk_size] for i in range(0, len(text), step)]

    def search(self, query, top_k=5):
        """Return the most relevant chunks for a query."""
        try:
            count = self.collection.count()
            if count == 0:
                return []
            results = self.collection.query(query_texts=[query], n_results=min(top_k, count))
            return results['documents'][0] if results['documents'] else []
        except Exception as e:
            print(f"Knowledge base search error: {e}")
            return []

    def list_documents(self):
        try:
            metadatas = self.collection.get(include=["metadatas"])['metadatas']
            return sorted({meta['source'] for meta in metadatas})
        except Exception as e:
            print(f"Knowledge base list error: {e}")
            return []

    def delete_document(self, doc_name):
        try:
            existing = self.collection.get(where={"source": doc_name})['ids']
            if not existing:
                return False, f"Document '{doc_name}' not found"
            self.collection.delete(ids=existing)
            return True, f"Document '{doc_name}' deleted"
        except Exception as e:
            return False, f"Error deleting: {e}"

    def get_context_from_documents(self, query, top_k=3):
        results = self.search(query, top_k)
        if not results:
            return ""
        return "📚 Document Context:\n" + "\n".join(f"- {r}" for r in results)
