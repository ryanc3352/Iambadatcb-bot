from pathlib import Path

from memory import MIN_RELEVANCE, get_chroma_client, relevant_documents


class KnowledgeBase:
    """RAG system for document indexing and search."""

    ALLOWED_TYPES = {'.pdf', '.docx', '.txt', '.md', '.csv', '.log', '.json', '.xml', '.yaml', '.yml',
                     '.toml', '.ini', '.cfg', '.html', '.css', '.js', '.ts', '.py', '.sql', '.sh', '.bat', '.ps1'}

    def __init__(self, db_path="./data/chroma"):
        self.client = get_chroma_client(str(db_path))
        # New databases use cosine distance; older ones (l2) still work
        self.collection = self.client.get_or_create_collection(name="documents", metadata={"hnsw:space": "cosine"})

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

    # PDF/Word libraries are imported only when needed, so a missing or broken
    # install only affects those file types instead of stopping the whole app
    def _extract_pdf(self, file_path):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("PDF support needs pypdf: pip install pypdf")
        reader = PdfReader(str(file_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def _extract_docx(self, file_path):
        try:
            from docx import Document
        except ImportError:
            # The old 'docx' package (Python 2) fails with "No module named 'exceptions'"
            raise RuntimeError("Word support needs python-docx: pip uninstall docx, then pip install python-docx")
        doc = Document(str(file_path))
        return "\n".join(para.text for para in doc.paragraphs)

    def _chunk_text(self, text, chunk_size=500, overlap=100):
        """Split text into overlapping chunks (the last chunk ends at the end of the text)."""
        chunks = []
        for start in range(0, len(text), chunk_size - overlap):
            chunks.append(text[start:start + chunk_size])
            if start + chunk_size >= len(text):
                break
        return chunks

    def search(self, query, top_k=5, min_similarity=None):
        """Return the most relevant chunks for a query (optionally only fairly similar ones)."""
        try:
            return relevant_documents(self.collection, query, top_k, min_similarity)
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

    def get_context_from_documents(self, query, top_k=3, min_similarity=MIN_RELEVANCE):
        """Relevant document text for the prompt, or "" if no document is about the question."""
        results = self.search(query, top_k, min_similarity)
        if not results:
            return ""
        return "📚 Document Context:\n" + "\n".join(f"- {r}" for r in results)
