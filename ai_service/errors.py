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
