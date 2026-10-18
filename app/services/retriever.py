from pathlib import Path
from typing import List, Optional

import chromadb

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma_db"
COLLECTION_NAME = "biology_syllabus"

_client = chromadb.PersistentClient(path=str(DB_PATH))
_collection = _client.get_collection(name=COLLECTION_NAME)


def get_context(topic: str, k: int = 4, unit_no: Optional[int] = None) -> List[dict]:
    """Search the syllabus chunks by meaning. Optionally limit to one unit."""
    kwargs = {"where": {"unit_no": unit_no}} if unit_no is not None else {}
    res = _collection.query(query_texts=[topic], n_results=k, **kwargs)
    return [
        {"text": doc, "meta": meta}
        for doc, meta in zip(res["documents"][0], res["metadatas"][0])
    ]