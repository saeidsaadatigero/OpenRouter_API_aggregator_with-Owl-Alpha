# main.py

import os
from services.openrouter_service import OpenRouterCodingService

def generate_custom_component(prompt: str, filename: str) -> None:
    """
    Invokes the OpenRouter agentic model to generate architecture components
    and saves the output strictly to a file.
    """
    # Using tencent/hy3-preview for deep reasoning workflows if needed, 
    # or sticking to openrouter/owl-alpha for fast agent tasks
    coder_service = OpenRouterCodingService(model_name="openrouter/owl-alpha")
    
    system_instruction = (
        "You are a Senior Python/AI Engineer. Output clean, robust, OOP-compliant code "
        "with strict type hints. Do NOT include explanations, markdown blocks, or text. "
        "Output ONLY valid, raw executable Python code."
    )
    
    print(f"Requesting engine component for: '{prompt}'...")
    try:
        generated_code = coder_service.generate_code(
            prompt=prompt, 
            system_instruction=system_instruction
        )
        
        # Ensure target directory exists
        os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else ".", exist_ok=True)
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(generated_code.strip().replace("```python", "").replace("```", ""))
            
        print(f"[SUCCESS] Component successfully compiled and saved to {filename}")
        
    except Exception as e:
        print(f"[ERROR] Failed to compile pipeline: {str(e)}")

if __name__ == "__main__":
    # Example: Generating a high-performance algorithmic trading order book parser
    target_prompt = "Create an optimized, async OrderBook class for crypto limit order books using SortedDict."
    generate_custom_component(prompt=target_prompt, filename="trading/order_book.py")