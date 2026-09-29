import pytest

from knowledge_base import KnowledgeBase
from memory import Memory, get_chroma_client


def make_pdf(path, text):
    """Write a minimal one-page PDF containing `text`."""
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


# ---------------- Memory

def test_memory_empty_search(tmp_path):
    assert Memory(tmp_path / "chroma").get_context_from_search("anything") == ""


def test_memory_add_search_and_clear(tmp_path):
    mem = Memory(tmp_path / "chroma")
    mem.add_conversation("What pizza do I like?", "You like mushroom pizza.", 1)
    mem.add_conversation("How do Python lists work?", "Lists are ordered and mutable.", 2)
    mem.add_conversation("How do Python lists work?", "Updated answer.", 2)  # same id: replaced
    assert mem.collection.count() == 2

    context = mem.get_context_from_search("pizza toppings", top_k=1)
    assert context.startswith("Related memory") and "pizza" in context
    assert "lists" not in context.lower() and "..." not in context
    # asking for more results than exist is fine
    assert mem.get_context_from_search("lists", top_k=10, min_similarity=None).count("\n") == 3  # header + 2
    # only memories about the question are used
    assert mem.get_context_from_search("lists", top_k=10).count("\n") == 2
    assert mem.get_context_from_search("what is the capital of France?") == ""

    mem.clear_memory()
    assert mem.collection.count() == 0


def test_chroma_client_is_shared(tmp_path):
    assert get_chroma_client(str(tmp_path)) is get_chroma_client(str(tmp_path))


# ---------------- Knowledge base

@pytest.fixture
def kb(tmp_path):
    return KnowledgeBase(tmp_path / "chroma")


def test_kb_add_search_list_delete(kb, tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("The office wifi password is stored in the blue folder. " * 20)
    ok, message = kb.add_document(doc)
    assert ok and "3 chunks" in message  # 1100 chars -> chunks at 0, 400, 800

    # re-adding replaces the old chunks instead of duplicating them
    doc.write_text("Short replacement text about the wifi.")
    assert kb.add_document(doc)[0]
    assert kb.collection.count() == 1

    assert kb.list_documents() == ["notes.txt"]
    assert "wifi" in kb.search("wifi", top_k=5)[0]
    assert kb.get_context_from_documents("wifi").startswith("📚 Document Context:")

    assert kb.delete_document("notes.txt") == (True, "Document 'notes.txt' deleted")
    assert kb.delete_document("notes.txt")[0] is False
    assert kb.list_documents() == [] and kb.search("wifi") == []
    assert kb.get_context_from_documents("wifi") == ""


def test_kb_rejects_bad_files(kb, tmp_path):
    exe = tmp_path / "virus.exe"
    exe.write_bytes(b"MZ")
    assert kb.add_document(exe) == (False, "File type '.exe' not supported")
    empty = tmp_path / "empty.txt"
    empty.write_text("   ")
    assert kb.add_document(empty) == (False, "Could not extract text")
    assert kb.add_document(tmp_path / "missing.txt")[0] is False


def test_kb_pdf_and_docx(kb, tmp_path):
    pdf = tmp_path / "report.pdf"
    make_pdf(pdf, "Quarterly revenue grew")
    assert kb.add_document(pdf)[0]
    assert "revenue" in kb.search("revenue")[0]

    from docx import Document
    word = tmp_path / "letter.docx"
    d = Document()
    d.add_paragraph("Dear Sam, the meeting moved to Friday.")
    d.save(word)
    assert kb.add_document(word)[0]
    assert set(kb.list_documents()) == {"report.pdf", "letter.docx"}

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert kb.add_document(broken)[0] is False


def test_kb_relevance(kb, tmp_path):
    doc = tmp_path / "keys.txt"
    doc.write_text("The spare key is hidden under the red flowerpot.")
    kb.add_document(doc)
    assert "flowerpot" in kb.get_context_from_documents("where is the spare key?")
    assert kb.get_context_from_documents("latest news about space") == ""
    assert kb.search("latest news about space")  # explicit searches still list the closest match


def test_old_l2_databases_still_filter(tmp_path):
    from memory import get_chroma_client, relevant_documents
    old = get_chroma_client(str(tmp_path / "old")).get_or_create_collection("documents")  # old default: l2
    old.add(ids=["1"], documents=["The spare key is hidden under the red flowerpot."])
    assert relevant_documents(old, "where is the key?", 3, 0.35)
    assert relevant_documents(old, "capital of France", 3, 0.35) == []


def test_kb_custom_name_and_chunking(kb, tmp_path):
    doc = tmp_path / "tmp123.md"
    doc.write_text("# Title\nbody")
    assert "'Real Name.md'" in kb.add_document(doc, doc_name="Real Name.md")[1]
    assert kb._chunk_text("abcdefghij", chunk_size=4, overlap=1) == ["abcd", "defg", "ghij"]
    assert kb._chunk_text("abc", chunk_size=4, overlap=1) == ["abc"]
