from typing import Any

from groq import AsyncGroq

from app.services.execution import before_paid_call, option


async def create_chat_completion(client: AsyncGroq, **kwargs: Any) -> Any:
    """Create a Groq chat completion with the configured application model."""
    await before_paid_call()
    return await client.chat.completions.create(model=option("groq_model"), **kwargs)
