import os

import chromadb
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

API_KEY = os.getenv("LLM_API_KEY")
MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "gemini-3.1-flash-lite")
COLLECTION_NAME = "biology_syllabus"

if not API_KEY:
    raise ValueError("LLM_API_KEY is missing in .env file")

client = genai.Client(api_key=API_KEY)

# Turns off the "automatic function calling" info notice
CONFIG = types.GenerateContentConfig(
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
)

chroma_client = chromadb.PersistentClient(path="app/data/chroma_db")
collection = chroma_client.get_collection(name=COLLECTION_NAME)


def page_label(meta: dict) -> str:
    start, end = meta.get("page_start"), meta.get("page_end")
    if start is None:
        return "Unknown"
    return str(start) if end is None or start == end else f"{start}-{end}"


def generate(prompt: str) -> str:
    try:
        response = client.models.generate_content(model=MODEL, contents=prompt, config=CONFIG)
    except Exception as primary_error:
        print(f"Primary model failed: {primary_error}")
        print("Trying fallback model...")
        response = client.models.generate_content(model=FALLBACK_MODEL, contents=prompt, config=CONFIG)
    return response.text or "No answer was generated."


def ask_biology(question: str) -> str:
    results = collection.query(query_texts=[question], n_results=3)

    context_parts = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        context_parts.append(f"[Unit {meta.get('unit_no', '?')}, Page {page_label(meta)}]\n{doc}")
    context = "\n\n".join(context_parts)

    prompt = f"""
You are a helpful A/L Biology study assistant.

Answer the question using only the context below.
Use simple English suitable for A/L students.
Do not invent information.
If the context does not contain the answer, clearly say that the provided material is insufficient.
Mention the relevant unit and page numbers in your answer.

Context:
{context}

Question:
{question}
"""
    return generate(prompt)


if __name__ == "__main__":
    print("A/L Biology RAG Chatbot")
    print("Type 'exit' to quit.\n")

    while True:
        question = input("You: ").strip()
        if question.lower() == "exit":
            break
        if not question:
            continue
        try:
            print("\nBot:", ask_biology(question), "\n")
        except Exception as error:
            print("Error:", error)