# services/openrouter_service.py

import os
from typing import List, Dict, Any, Optional
from decouple import config
from openai import OpenAI
from openai.types.chat import ChatCompletion

class OpenRouterCodingService:
    """
    Service layer to handle communication with OpenRouter API
    utilizing the OpenAI compatible client interface.
    """
    
    def __init__(self, model_name: str = "openrouter/owl-alpha") -> None:
        self.api_key: str = config("OPENROUTER_API_KEY", default="")
        self.base_url: str = "https://openrouter.ai/api/v1"
        self.model_name: str = model_name
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is not set in the environment variables.")
            
        # Initialize OpenAI client pointed to OpenRouter infrastructure
        self.client: OpenAI = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://localhost:3000",  # Optional: For OpenRouter analytics
                "X-OpenRouter-Title": "Local Code Assistant" # Optional
            }
        )

    def generate_code(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """
        Sends a coding prompt to the specified OpenRouter model and returns the text response.
        """
        messages: List[Dict[str, str]] = []
        
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
            
        messages.append({"role": "user", "content": prompt})
        
        try:
            response: ChatCompletion = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages, # type: ignore
                temperature=0.2,   # Low temperature for deterministic code generation
            )
            return response.choices[0].message.content or ""
            
        except Exception as e:
            # Multi-model DB logging or production log handling should be triggered here
            print(f"[DB LOG] Error invoking OpenRouter model: {str(e)}")
            raise e