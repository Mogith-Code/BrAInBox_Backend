"""RAG: ask Biology questions in the terminal, answered from the ingested sources.

Ported from Udith's rag_chat.py (ChromaDB -> shared RAG layer, prompt -> versioned template).
Uses the real LLM when GEMINI_API_KEY is set and USE_FAKE_AI=false; otherwise the fake echo LLM.

    python scripts/rag_chat.py
    python scripts/rag_chat.py --unit 2
"""

import argparse
import asyncio

import _bootstrap  # noqa: F401

from ai_service.prompts import render_prompt
from ai_service.providers import get_llm, provider_names
from ai_service.rag.context_builder import build_context
from ai_service.rag.ingestion.pipeline import unit_id_for_number
from ai_service.rag.retrieval.retriever import retrieve
from shared.db.session import SessionLocal


async def ask(question: str, unit_number: int | None) -> str:
    async with SessionLocal() as session:
        unit_id = await unit_id_for_number(session, unit_number) if unit_number else None
        chunks = await retrieve(question, unit_id=unit_id, k=3, session=session)
    if not chunks:
        return "No sources found. Did you run scripts/ingest_documents.py?"
    context = build_context(chunks)
    prompt = render_prompt("rag/ask", 1, question=question, context=context.text)
    answer = await get_llm().generate(prompt, prompt_name="rag/ask.v1")
    sources = "; ".join(
        f"[{c.ref}] {c.document_title}" + (f" p.{c.page}" if c.page else "")
        for c in context.citations
    )
    return f"{answer}\n\nSources: {sources}"


async def chat(unit_number: int | None) -> None:
    print(f"A/L Biology RAG chat  (providers: {provider_names()})")
    print("Type 'exit' to quit.\n")
    while True:
        question = input("You: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue
        try:
            print("\nBot:", await ask(question, unit_number), "\n")
        except Exception as error:
            print("Error:", error)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the RAG sources")
    parser.add_argument("--unit", type=int, help="only search this unit (1-10)")
    asyncio.run(chat(parser.parse_args().unit))


if __name__ == "__main__":
    main()
