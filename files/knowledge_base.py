import re
from pathlib import Path

from memory import MIN_RELEVANCE, get_chroma_client, relevant_documents, similarity

CHUNK_SIZE, CHUNK_OVERLAP = 500, 100

# Questions about the documents themselves: "what's in my knowledge base?", "quiz me on the PDF I uploaded"
DOCUMENT_WORDS = re.compile(r"\b(?:documents?|docs?|knowledge ?base|uploaded|uploads?|pdfs?|word files?)\b",
                            re.IGNORECASE)


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

        chunks = self._chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
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

    def document_start(self, doc_name, max_chars=1500):
        """The first part of a document's text."""
        try:
            chunks = self.collection.get(ids=[f"{doc_name}_{i}" for i in range(4)])
        except Exception:
            return ""
        by_id = dict(zip(chunks['ids'], chunks['documents']))
        text = ""
        for i in range(4):
            chunk = by_id.get(f"{doc_name}_{i}")
            if chunk is None:
                break
            text += chunk if i == 0 else chunk[CHUNK_OVERLAP:]  # chunks overlap
        return text[:max_chars] + (" [...]" if len(text) > max_chars else "")

    def named_documents(self, query, names):
        """Documents the question names ("summarize recipes.pdf", "what's in my recipes doc")."""
        text = query.lower()
        return [name for name in names
                if name.lower() in text or (len(Path(name).stem) >= 4 and Path(name).stem.lower() in text)]

    def get_context_from_documents(self, query, top_k=3, min_similarity=MIN_RELEVANCE):
        """Document text for the prompt, or "" if no document is about the question.

        Passages about the question are found by meaning. A question about the documents
        themselves ("what's in my knowledge base?", "quiz me on my PDF") doesn't look like any
        passage, so then the list of documents and the start of the named (or first) ones are added.
        """
        names = self.list_documents()
        if not names:
            return ""
        parts = []
        named = self.named_documents(query, names)
        if named or DOCUMENT_WORDS.search(query):
            parts.append("Documents in the user's knowledge base (the complete list): " + ", ".join(names))
            for name in (named or names)[:3]:
                start = self.document_start(name)
                if start:
                    parts.append(f"Start of {name}:\n{start}")
        passages = self.search_with_sources(query, top_k, min_similarity)
        if passages:
            parts.append("Passages about the question:\n" + "\n".join(f"- [{source}] {text}"
                                                                      for source, text in passages))
        return "📚 Document Context:\n" + "\n\n".join(parts) if parts else ""

    def search_with_sources(self, query, top_k=3, min_similarity=MIN_RELEVANCE):
        """[(document name, passage)] for the passages at least min_similarity similar to the query."""
        try:
            count = self.collection.count()
            if not count:
                return []
            results = self.collection.query(query_texts=[query], n_results=min(top_k, count),
                                            include=["documents", "metadatas", "distances"])
        except Exception as e:
            print(f"Knowledge base search error: {e}")
            return []
        space = (self.collection.metadata or {}).get("hnsw:space", "l2")
        return [(meta.get('source', '?'), doc)
                for doc, meta, distance in zip(results['documents'][0], results['metadatas'][0],
                                               results['distances'][0])
                if similarity(distance, space) >= min_similarity]
