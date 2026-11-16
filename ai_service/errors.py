"""Errors a pipeline raises when the problem is the student's input, not the service.

The ai_service answers them with 422 {"error": {"code", "message"}} (see main.py), and the api
passes the code and message on to the app (api/core/ai_client.py).
"""


class UserInputError(ValueError):
    """Bad input, e.g. empty notes. `message` is safe to show to the student."""

    code = "INVALID_INPUT"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class AIOutputError(UserInputError):
    """The LLM's answer stayed invalid after the retry (e.g. not JSON, no valid blocks).

    Not the student's fault, but it goes through the same 422 path so the api keeps the code
    and the clear message on the failed job instead of a generic "AI service unavailable".
    """

    code = "INVALID_AI_OUTPUT"
