import unittest
from unittest.mock import patch

from app.core.config import settings

try:
    from app.services.llm import create_chat_completion
except ImportError:
    create_chat_completion = None


class _FakeCompletions:
    def __init__(self) -> None:
        self.received_kwargs = None
        self.response = object()

    async def create(self, **kwargs):
        self.received_kwargs = kwargs
        return self.response


class _FakeClient:
    def __init__(self) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions()})()


class GroqModelConfigurationTest(unittest.IsolatedAsyncioTestCase):
    async def test_completion_uses_the_configured_model(self) -> None:
        self.assertIsNotNone(
            create_chat_completion,
            "app.services.llm.create_chat_completion must exist",
        )
        client = _FakeClient()

        with patch.object(settings, "groq_model", "validation-model"):
            response = await create_chat_completion(
                client,
                messages=[{"role": "user", "content": "Return JSON"}],
                max_tokens=100,
            )

        self.assertIs(response, client.chat.completions.response)
        self.assertEqual(
            client.chat.completions.received_kwargs["model"],
            "validation-model",
        )


if __name__ == "__main__":
    unittest.main()
