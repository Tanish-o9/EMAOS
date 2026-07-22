"""
EMAOS — Semantic Memory
Vector similarity search using FAISS + sentence-transformers.
Falls back to PostgreSQL pgvector when FAISS index is cold.
"""
import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://emaos:emaos_secret@localhost:5432/emaos")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
FAISS_INDEX_PATH = Path(os.getenv("FAISS_INDEX_PATH", "c:/Users/tanis/OneDrive/Desktop/EMAOS/emaos/faiss_memory.index"))
FAISS_METADATA_PATH = Path(os.getenv("FAISS_METADATA_PATH", "c:/Users/tanis/OneDrive/Desktop/EMAOS/emaos/faiss_metadata.pkl"))

# Lazy imports to avoid slow startup
_model = None
_faiss = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"[SEMANTIC-MEMORY] Loading embedding model: {EMBEDDING_MODEL}")
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_faiss():
    global _faiss
    if _faiss is None:
        import faiss as _f
        _faiss = _f
    return _faiss


def _get_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


class SemanticMemory:
    """
    Stores text → embedding pairs and performs cosine similarity search.
    Uses FAISS for fast in-memory search and pgvector for persistent storage.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim
        self._index = None
        self._id_map: List[str] = []        # FAISS index → DB id
        self._content_map: List[str] = []   # FAISS index → content text
        self._agent_map: List[str] = []     # FAISS index → agent name
        self._meta_map: List[dict] = []     # FAISS index → metadata dict

    def _init_index(self):
        if self._index is None:
            faiss = _get_faiss()
            # Cosine similarity uses Inner Product on normalized vectors
            self._index = faiss.IndexFlatIP(self.dim)

    # ─── Embedding ────────────────────────────────────────────────
    def embed(self, text: str) -> np.ndarray:
        model = _get_model()
        vec = model.encode([text], normalize_embeddings=True)
        return vec.astype("float32")

    # ─── Write ────────────────────────────────────────────────────
    def add(
        self,
        text: str,
        agent_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        self._init_index()
        meta = metadata or {}
        vec = self.embed(text)
        vec_list = vec[0].tolist()
        vec_str = json.dumps(vec_list)

        sql = """
            INSERT INTO semantic_memory (agent_name, content, embedding, metadata)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """
        db_id = ""
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (agent_name, text, vec_str, json.dumps(meta)))
                    row = cur.fetchone()
                    if row:
                        db_id = str(row[0])
                conn.commit()

            # Add to local FAISS index
            if db_id:
                self._index.add(vec)
                self._id_map.append(db_id)
                self._content_map.append(text)
                self._agent_map.append(agent_name or "unknown")
                self._meta_map.append(meta)
                self.save_to_disk()
                logger.info(f"[SEMANTIC-MEMORY] Added memory ID: {db_id}")
        except Exception as exc:
            logger.error(f"[SEMANTIC-MEMORY] Failed to add memory: {exc}")
        
        return db_id

    # ─── Search ───────────────────────────────────────────────────
    def search(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        self._init_index()
        if self._index.ntotal == 0:
            logger.warning("[SEMANTIC-MEMORY] FAISS index is empty. Warmed from DB first.")
            self.warm_from_db()
            if self._index.ntotal == 0:
                return []

        try:
            query_vec = self.embed(query)
            scores, indices = self._index.search(query_vec, min(limit, self._index.ntotal))
            
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self._id_map):
                    continue
                if score < min_score:
                    continue
                results.append({
                    "id": self._id_map[idx],
                    "agent_name": self._agent_map[idx],
                    "content": self._content_map[idx],
                    "score": float(score),
                    "metadata": self._meta_map[idx]
                })
            return results
        except Exception as exc:
            logger.error(f"[SEMANTIC-MEMORY] Search failed: {exc}")
            return []

    # ─── Warm from DB ──────────────────────────────────────────────
    def warm_from_db(self, limit: int = 5000) -> int:
        self._init_index()
        sql = """
            SELECT id, agent_name, content, embedding, metadata
            FROM semantic_memory
            ORDER BY created_at DESC
            LIMIT %s
        """
        count = 0
        try:
            with _get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, (limit,))
                    rows = cur.fetchall()
            
            if not rows:
                return 0
            
            # Clear old lists
            self._id_map.clear()
            self._content_map.clear()
            self._agent_map.clear()
            self._meta_map.clear()
            
            # Create a new index
            faiss = _get_faiss()
            self._index = faiss.IndexFlatIP(self.dim)
            
            vectors = []
            for row in rows:
                db_id = str(row["id"])
                agent_name = row["agent_name"] or "unknown"
                content = row["content"]
                meta = row["metadata"] or {}
                
                try:
                    if row["embedding"]:
                        vec_list = json.loads(row["embedding"])
                        vec = np.array(vec_list, dtype="float32")
                    else:
                        vec = self.embed(content)[0]
                except Exception:
                    vec = self.embed(content)[0]
                
                vectors.append(vec)
                self._id_map.append(db_id)
                self._content_map.append(content)
                self._agent_map.append(agent_name)
                self._meta_map.append(meta)
                count += 1
            
            if vectors:
                np_vecs = np.vstack(vectors).astype("float32")
                self._index.add(np_vecs)
                self.save_to_disk()
                logger.info(f"[SEMANTIC-MEMORY] FAISS index warmed with {count} items")
        except Exception as exc:
            logger.error(f"[SEMANTIC-MEMORY] Failed to warm index: {exc}")
        
        return count

    # ─── Save/Load disk cache ──────────────────────────────────────
    def save_to_disk(self) -> None:
        self._init_index()
        if self._index.ntotal == 0:
            return
        try:
            faiss = _get_faiss()
            FAISS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, str(FAISS_INDEX_PATH))
            
            meta_data = {
                "id_map": self._id_map,
                "content_map": self._content_map,
                "agent_map": self._agent_map,
                "meta_map": self._meta_map
            }
            with open(FAISS_METADATA_PATH, "wb") as f:
                pickle.dump(meta_data, f)
        except Exception as exc:
            logger.error(f"[SEMANTIC-MEMORY] Save failed: {exc}")

    def load_from_disk(self) -> bool:
        if not FAISS_INDEX_PATH.exists() or not FAISS_METADATA_PATH.exists():
            return False
        try:
            faiss = _get_faiss()
            self._index = faiss.read_index(str(FAISS_INDEX_PATH))
            with open(FAISS_METADATA_PATH, "rb") as f:
                meta_data = pickle.load(f)
            self._id_map = meta_data["id_map"]
            self._content_map = meta_data["content_map"]
            self._agent_map = meta_data["agent_map"]
            self._meta_map = meta_data["meta_map"]
            logger.info(f"[SEMANTIC-MEMORY] FAISS index loaded from disk ({self._index.ntotal} items)")
            return True
        except Exception as exc:
            logger.error(f"[SEMANTIC-MEMORY] Load failed: {exc}")
            return False


semantic_memory = SemanticMemory()
