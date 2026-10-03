from typing import Any

from groq import AsyncGroq

from app.core.config import settings


async def create_chat_completion(client: AsyncGroq, **kwargs: Any) -> Any:
    """Create a Groq chat completion with the configured application model."""
    return await client.chat.completions.create(model=settings.groq_model, **kwargs)
