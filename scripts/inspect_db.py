from collections import Counter

import chromadb

COLLECTION_NAME = "biology_syllabus"

c = chromadb.PersistentClient(path="app/data/chroma_db").get_collection(COLLECTION_NAME)
data = c.get(limit=c.count(), include=["documents", "metadatas"])
docs, metas = data["documents"], data["metadatas"]

print("Total chunks:", len(docs), "\n")

per_unit = Counter((m.get("unit_no"), m.get("unit")) for m in metas)
print("Chunks per unit:")
for (no, name), n in sorted(per_unit.items(), key=lambda x: (x[0][0] is None, x[0][0])):
    print(f"  Unit {no}: {name}  ->  {n} chunks")

print("\nChecks:")
for phrase in ("rights reserved", "national institute", "resource book"):
    print(f"  chunks containing '{phrase}':", sum(phrase in d.lower() for d in docs))

lengths = [len(d.split()) for d in docs]
print(f"  words per chunk: min {min(lengths)}, max {max(lengths)}, avg {sum(lengths) // len(lengths)}")
print("  very short chunks (< 80 words):", sum(l < 80 for l in lengths))