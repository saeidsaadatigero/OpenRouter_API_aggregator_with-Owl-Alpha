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
            
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://localhost:8000",
                "X-OpenRouter-Title": "Agentic Studio Workspace"
            }
        )

    async def generate_code_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        system_instruction = self._get_active_instruction_content()
        
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
                stream=True
            )
            
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"[OPENROUTER-ERROR] Pipeline broken during upstream processing: {str(e)}")
            raise e
        
    async def generate_safe_filename(self, user_prompt: str) -> str:
        try:
            system_instruction = (
                "Analyze the user request and output ONLY a single valid, safe filename with an appropriate extension "
                "that matches the programming language or context. Do NOT output code, introduction, quotes, or markdown. "
                "Example: data_parser.py"
            )
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": f"Generate a filename for this request: {user_prompt}"}
                ],
                temperature=0.1,
                max_tokens=20,
                stream=False
            )
            generated_name = response.choices[0].message.content.strip()
            generated_name = generated_name.replace("`", "").replace("'", "").replace('"', "")
            return generated_name if generated_name else "component.py"
        except Exception as llm_err:
            logging.getLogger(__name__).error(f"[AUTO-NAME-ERROR] Failed to infer filename: {str(llm_err)}")
            return "component.py"

    def _get_active_instruction_content(self) -> str:
        try:
            from database import SessionLocal
            from services.instruction_service import InstructionService
            
            db = SessionLocal()
            try:
                instruction_service = InstructionService(db)
                instruction = instruction_service.get_active_instruction()
                if instruction:
                    return instruction.content
                return self._get_default_instruction()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[INSTRUCTION-ERROR] Failed to get active instruction: {e}")
            return self._get_default_instruction()

    def _get_default_instruction(self) -> str:
        return """You are OWL, a Senior Python/AI Engineer and coding assistant. 
Answer clearly and helpfully. Use markdown for code blocks."""
