"""Vector store management with ChromaDB.

Provides two indexing paths:

* ``build_vector_store()`` – full rebuild from the ``documents/`` directory
  (used for initial setup, manual rebuild, or system-document refresh).
* ``add_file_to_store()`` – incremental add for a single uploaded file.

Both functions share the same embedding model and Chroma collection.
"""

import os
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from utils.document_loader import load_documents
from utils.text_splitter import split_text

# ---------------------------------------------------------------------------
# Shared resources
# ---------------------------------------------------------------------------

model = SentenceTransformer(
    "BAAI/bge-base-zh-v1.5",
    local_files_only=True,
)

client = chromadb.PersistentClient(path="vector_db")
collection = client.get_or_create_collection("knowledge")


# ---------------------------------------------------------------------------
# Full rebuild
# ---------------------------------------------------------------------------

def build_vector_store() -> None:
    """Wipe the collection and re-index every document under ``documents/``."""

    old = collection.get()
    if old["ids"]:
        collection.delete(ids=old["ids"])

    documents = load_documents()
    print("读取文档数量:", len(documents))

    chunks = split_text(documents)
    print("切片数量:", len(chunks))

    if not chunks:
        print("没有可写入的文档切片，已清空向量库")
        return

    _index_chunks(chunks)


def sync_system_documents(folder_path: str = "documents") -> int:
    """Incrementally refresh only built-in (``user_id=system``) documents.

    User-uploaded vectors stay intact.  This is safe to call after adding or
    editing files in ``documents/`` and replaces the previous all-or-nothing
    rebuild workflow for system knowledge.
    """
    old = collection.get(where={"user_id": "system"})
    if old["ids"]:
        collection.delete(ids=old["ids"])

    documents = load_documents(folder_path)
    chunks = split_text(documents)
    if not chunks:
        return 0
    _index_chunks(chunks)
    return len(chunks)


# ---------------------------------------------------------------------------
# Incremental add
# ---------------------------------------------------------------------------

def add_file_to_store(filepath: str, filename: str, user_id: int) -> int:
    """Index a single file without touching the rest of the collection.

    Returns the number of chunks added.
    """
    # Remove any existing vectors for this stored filename / user combo
    _remove_by_stored_filename(os.path.basename(filepath), str(user_id))

    content = _read_file_content(filepath)
    if not content.strip():
        return 0

    chunks = split_text(
        [
            {
                "text": content,
                "filename": filename,
                "stored_filename": os.path.basename(filepath),
                "user_id": str(user_id),
            }
        ]
    )

    if not chunks:
        return 0

    _index_chunks(chunks)
    return len(chunks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _index_chunks(chunks: list[dict]) -> None:
    """Embed and add a list of chunks to the Chroma collection."""
    texts = [chunk["text"] for chunk in chunks]
    vectors = model.encode(texts, normalize_embeddings=True).tolist()

    ids = []
    metadatas = []
    for i, chunk in enumerate(chunks):
        ids.append(_next_chunk_id(chunk))
        metadatas.append(
            {
                "filename": chunk["filename"],
                "stored_filename": chunk["stored_filename"],
                "source": "system" if chunk["user_id"] == "system" else "user",
                "user_id": str(chunk["user_id"]),
                "section_title": chunk.get("section_title", "文档摘要"),
                "chunk_index": int(chunk.get("chunk_index", i)),
            }
        )

    collection.add(ids=ids, documents=texts, embeddings=vectors, metadatas=metadatas)
    print(f"向量库已添加 {len(chunks)} 个切片")


def _next_chunk_id(chunk: dict) -> str:
    """Generate a unique id for a chunk."""
    import uuid
    return f"{chunk['stored_filename']}__{uuid.uuid4().hex[:12]}"


def _remove_by_stored_filename(stored_filename: str, user_id: str) -> None:
    """Delete all vectors matching a stored filename + user_id."""
    try:
        collection.delete(
            where={
                "stored_filename": stored_filename,
                "user_id": user_id,
            }
        )
    except Exception as exc:
        print(f"删除旧向量失败（可忽略）: {exc}")


def _read_file_content(filepath: str) -> str:
    """Read a file with multi-encoding fallback (mirrors document_loader)."""
    import codecs
    encodings = (
        "utf-8", "utf-8-sig", "gb18030", "gbk",
        "utf-16", "utf-16-le", "utf-16-be", "big5",
    )
    with open(filepath, "rb") as f:
        raw = f.read()

    for enc in encodings:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue

    raise UnicodeDecodeError("text", raw, 0, len(raw),
                             f"无法读取文件: {os.path.basename(filepath)}")


# ---------------------------------------------------------------------------
# CLI entry point for manual rebuild
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_vector_store()
