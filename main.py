# main.py

from services.openrouter_service import OpenRouterCodingService

def main() -> None:
    # Using the free high-performance owl-alpha model highlighted in the team chat
    coder_service = OpenRouterCodingService(model_name="openrouter/owl-alpha")
    
    system_prompt = "You are an expert Python engineer. Output clean, PEP8 compliant code with type hints."
    user_prompt = "Write a high-performance singleton database connection pool in Python using asyncio."
    
    print("Sending request to OpenRouter (Owl-Alpha)...")
    try:
        generated_code = coder_service.generate_code(
            prompt=user_prompt, 
            system_instruction=system_prompt
        )
        print("\n--- Generated Output ---")
        print(generated_code)
    except Exception:
        print("Execution failed. Check your API key and connection network.")

if __name__ == "__main__":
    main()