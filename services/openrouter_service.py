# services/openrouter_service.py
import os
import logging
from typing import AsyncGenerator
from decouple import config
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenRouterCodingService:
    def __init__(self, model_name: str = "openrouter/owl-alpha") -> None:
        self.api_key: str = config("OPENROUTER_API_KEY", default="")
        self.base_url: str = "https://openrouter.ai/api/v1"
        self.model_name: str = model_name
        
        if not self.api_key:
            logger.error("[CRITICAL] OPENROUTER_API_KEY configuration token is missing from environment.")
            raise ValueError("OPENROUTER_API_KEY is missing from environment.")
            
        # Upgrade client stack to AsyncOpenAI for non-blocking stream handling
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://localhost:8000",
                "X-OpenRouter-Title": "Agentic Studio Workspace"
            }
        )

    async def generate_code_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Invokes upstream cluster and yields tokens asynchronously."""
        system_instruction = (
            "You are OWL, a Senior Python/AI Engineer. Output clean, robust, OOP-compliant code "
            "with strict type hints. Do NOT include markdown blocks like ```python or ```, "
            "do NOT include conversational explanations or prose text. Output ONLY valid, raw executable code."
        )
        
        logger.info(f"[OPENROUTER] Opening upstream network socket stream for model: {self.model_name}")
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=4000,
                stream=True  # Enables raw token chunk streaming
            )
            
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"[OPENROUTER-ERROR] Pipeline broken during upstream processing: {str(e)}")
            raise e