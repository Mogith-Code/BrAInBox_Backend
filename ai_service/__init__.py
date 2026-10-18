"""SERVICE 2 - the internal BrAInBox AI service.

The ONLY place that calls AI providers (Gemini, embeddings, OCR, image generation).
It is not public: only the api calls it, with the X-Service-Token header.
"""
