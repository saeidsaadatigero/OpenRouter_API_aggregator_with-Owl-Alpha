# services/openrouter_service.py
import os
from decouple import config
from openai import OpenAI

class OpenRouterCodingService:
    def __init__(self, model_name: str = "openrouter/owl-alpha") -> None:
        self.api_key: str = config("OPENROUTER_API_KEY", default="")
        self.base_url: str = "https://openrouter.ai/api/v1"
        self.model_name: str = model_name
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is missing from environment layout.")
            
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://localhost:8000",
                "X-OpenRouter-Title": "Agentic Studio Workspace"
            }
        )

    def generate_code(self, prompt: str) -> str:
        system_instruction = (
            "You are a Senior Python/AI Engineer. Output clean, robust, OOP-compliant code "
            "with strict type hints. Do NOT include markdown blocks like ```python or ```, "
            "do NOT include conversational explanations or prose text. Output ONLY valid, raw executable code."
        )
        
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content or ""
