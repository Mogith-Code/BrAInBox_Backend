import os
from dotenv import load_dotenv

load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.8-flash")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "")
DEBUG_SHOW_ANSWERS = os.getenv("DEBUG_SHOW_ANSWERS", "false").lower() == "true"