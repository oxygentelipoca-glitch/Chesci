"""Shared local resources, opened only when document retrieval needs them."""
from functools import lru_cache


@lru_cache(maxsize=1)
def get_collection():
    import chromadb
    return chromadb.PersistentClient(path="vector_db").get_or_create_collection("knowledge")


@lru_cache(maxsize=1)
def get_embedding_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("BAAI/bge-base-zh-v1.5", local_files_only=True)
