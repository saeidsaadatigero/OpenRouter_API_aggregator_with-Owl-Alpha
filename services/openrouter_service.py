# services/openrouter_service.py
import logging
from typing import AsyncGenerator, List, Dict
from openai import AsyncOpenAI
from decouple import config

logger = logging.getLogger(__name__)

class OpenRouterCodingService:
    def __init__(self, model_name: str = "openrouter/owl-alpha") -> None:
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=config("OPENROUTER_API_KEY", default="")
        )
        self.model_name = model_name

    async def generate_conversational_stream(
        self, 
        history_messages: List[Dict[str, str]], 
        latest_prompt: str
    ) -> AsyncGenerator[str, None]:
        """Compiles historical interaction payload and yields streaming tokens."""
        system_instruction = (
            "You are OWL, an expert AI engineer. Maintain consistent state across the chat history. "
            "Output ONLY valid raw executable code when requested, fitting the historical context."
        )
        
        # Inject structural thread context
        formatted_messages = [{"role": "system", "content": system_instruction}]
        
        for msg in history_messages:
            formatted_messages.append({"role": msg["role"], "content": msg["content"]})
            
        formatted_messages.append({"role": "user", "content": latest_prompt})

        try:
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=formatted_messages,
                temperature=0.2,
                stream=True
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"[STREAM-ERROR] Multi-turn pipeline failed: {str(e)}")
            raise e