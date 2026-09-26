"""Chroma vector store: one collection per project codebase plus a shared
collection used for semantic search across all submissions.

Embeddings default to Chroma's bundled ONNX all-MiniLM-L6-v2 model, but when an
OpenAI-compatible embeddings endpoint is configured (EMBEDDING_*) a remote call is
used instead: loading the ONNX model in-process needs 600MB+ of RAM and can stall
on first download, which is fatal on small hosts. Set CHROMA_HOST to use a shared
Chroma server when running several workers.
"""

import hashlib
import logging
import os
import threading
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings

log = logging.getLogger(__name__)

PROJECTS_COLLECTION = "evalio-projects"
_client: Any = None
_lock = threading.Lock()


def _remote_embeddings_enabled() -> bool:
    return bool(settings.embedding_model and (settings.embedding_api_key or settings.embedding_base_url))


def embedding_signature() -> str:
    """Short digest of the *effective* embedding configuration.

    Vectors from different models are incompatible, so each configuration gets
    its own collections instead of failing on a dimension mismatch when the
    embedding provider changes. Falls back to "chroma-default" whenever the
    bundled local model is used, so a model id without an endpoint never names
    collections as if they held remote vectors.
    """
    basis = f"{settings.embedding_base_url}|{settings.embedding_model}" if _remote_embeddings_enabled() else "chroma-default"
    return hashlib.sha1(basis.encode()).hexdigest()[:8]


@lru_cache(maxsize=1)
def get_embedding_function():
    """Remote OpenAI-compatible embeddings, or None to use Chroma's bundled model."""
    if not _remote_embeddings_enabled():
        return None
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

    return OpenAIEmbeddingFunction(
        api_key=settings.embedding_api_key or None,
        model_name=settings.embedding_model,
        api_base=settings.embedding_base_url or None,
        # Chroma persists the config (without the key) and rebuilds it from this
        # env var, so pass the name it should read back.
        api_key_env_var="EMBEDDING_API_KEY",
    )


def projects_collection_name() -> str:
    return f"{PROJECTS_COLLECTION}-{embedding_signature()}"


def get_client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                chroma_settings = ChromaSettings(anonymized_telemetry=False)
                if settings.chroma_host:
                    _client = chromadb.HttpClient(
                        host=settings.chroma_host,
                        port=settings.chroma_port,
                        settings=chroma_settings,
                    )
                else:
                    os.makedirs(settings.chroma_dir, exist_ok=True)
                    _client = chromadb.PersistentClient(
                        path=settings.chroma_dir, settings=chroma_settings
                    )
    return _client


def code_collection_name(project_id: str) -> str:
    return f"code-{embedding_signature()}-{project_id}"


def reset_code_collection(project_id: str):
    client = get_client()
    name = code_collection_name(project_id)
    try:
        client.delete_collection(name)
    except Exception:
        pass
    return client.create_collection(
        name, metadata={"hnsw:space": "cosine"}, embedding_function=get_embedding_function()
    )


def get_code_collection(project_id: str):
    try:
        return get_client().get_collection(
            code_collection_name(project_id), embedding_function=get_embedding_function()
        )
    except Exception:
        return None


def delete_project_vectors(project_id: str) -> None:
    client = get_client()
    try:
        client.delete_collection(code_collection_name(project_id))
    except Exception:
        pass
    try:
        _projects_collection().delete(ids=[project_id])
    except Exception:
        pass


def add_chunks(collection, chunks: list[dict], batch_size: int = 64) -> None:
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        collection.add(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )


def query_code(
    project_id: str, queries: list[str], k: int = 6, max_chars: int = 9000, code_only: bool = False
) -> list[dict]:
    """Retrieve distinct chunks relevant to any of `queries`.

    Prose (README, specs) matches natural-language queries best, so reviews of the
    implementation pass `code_only=True` to only look at source files."""
    collection = get_code_collection(project_id)
    if collection is None or not queries:
        return []
    count = collection.count()
    if count == 0:
        return []
    where = {"kind": "code"} if code_only else None
    try:
        result = collection.query(query_texts=queries, n_results=min(k, count), where=where)
    except Exception:
        # Collections indexed before chunks carried a "kind" tag
        result = collection.query(query_texts=queries, n_results=min(k, count))
    if code_only and not any(result["ids"]):
        result = collection.query(query_texts=queries, n_results=min(k, count))
    seen: dict[str, dict] = {}
    for docs, metas, dists in zip(result["documents"], result["metadatas"], result["distances"]):
        for doc, meta, dist in zip(docs, metas, dists):
            key = f"{meta.get('path')}:{meta.get('start_line')}"
            if key not in seen or dist < seen[key]["distance"]:
                seen[key] = {
                    "path": meta.get("path", "?"),
                    "start_line": meta.get("start_line", 0),
                    "end_line": meta.get("end_line", 0),
                    "text": doc,
                    "distance": dist,
                }
    ranked = sorted(seen.values(), key=lambda c: c["distance"])
    out, used = [], 0
    for chunk in ranked:
        if used + len(chunk["text"]) > max_chars and out:
            break
        out.append(chunk)
        used += len(chunk["text"])
    return out


def format_chunks(chunks: list[dict]) -> str:
    return "\n\n".join(
        f"### {c['path']} (lines {c['start_line']}-{c['end_line']})\n{c['text']}" for c in chunks
    )


# ---------- cross-project semantic search ----------


def _projects_collection():
    return get_client().get_or_create_collection(
        projects_collection_name(),
        metadata={"hnsw:space": "cosine"},
        embedding_function=get_embedding_function(),
    )


def upsert_project_document(project_id: str, text: str, hackathon_id: int | None) -> None:
    try:
        _projects_collection().upsert(
            ids=[project_id],
            documents=[text[:6000]],
            metadatas=[{"hackathon_id": int(hackathon_id) if hackathon_id else -1}],
        )
    except Exception as exc:
        log.warning("Could not index project %s for search: %s", project_id, exc)


def search_projects(query: str, k: int = 12, hackathon_id: int | None = None) -> list[tuple[str, float]]:
    collection = _projects_collection()
    count = collection.count()
    if count == 0:
        return []
    where = {"hackathon_id": int(hackathon_id)} if hackathon_id else None
    result = collection.query(query_texts=[query], n_results=min(k, count), where=where)
    ids = result["ids"][0]
    # cosine distance (0..2) -> similarity (1..-1), clamped to 0..1
    return [(pid, max(0.0, min(1.0, 1 - dist))) for pid, dist in zip(ids, result["distances"][0])]
