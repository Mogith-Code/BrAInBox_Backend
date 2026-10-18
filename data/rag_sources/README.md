# RAG source documents

Put **admin-approved** documents here, in the folder for their type. Then run
`python scripts/ingest_documents.py` (see `ai_service/rag/README.md`).

| Folder | Source type | Examples |
|---|---|---|
| `syllabus/` | `syllabus` | NIE G.C.E. A/L Biology syllabus |
| `teacher_guides/` | `teacher_guide` | NIE teacher's guides |
| `approved_notes/` | `approved_note` | Notes reviewed by an admin |
| `marking_schemes/` | `marking_scheme` | Past-paper marking schemes |

Supported formats: `.pdf`, `.docx`, `.txt` and `.md`.

> **Copyright.** Do not commit copyrighted documents. `.gitignore` ignores everything in these folders
> except `.gitkeep`, this README and files named `sample_*` (small samples we wrote ourselves for tests and demos).
> Share real documents through the team drive, or upload them with the admin portal.
