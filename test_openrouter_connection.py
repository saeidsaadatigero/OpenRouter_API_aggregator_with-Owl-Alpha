# test_openrouter_connection.py
import asyncio
import os
from openai import AsyncOpenAI
from decouple import config

# خواندن کلید از .env
API_KEY = config("OPENROUTER_API_KEY", default="")
BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openrouter/owl-alpha"

async def test():
    print(f"🔑 API Key loaded: {'✅ Yes' if API_KEY else '❌ No'}")
    print(f"🔑 Key starts with: {API_KEY[:20]}..." if API_KEY else "🔑 Key is EMPTY!")
    
    if not API_KEY:
        print("❌ No API key found in .env file!")
        print("Please check your .env file has: OPENROUTER_API_KEY=sk-or-v1-...")
        return
    
    client = AsyncOpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout=60.0,
        max_retries=3,
        default_headers={
            "HTTP-Referer": "https://localhost:8000",
            "X-OpenRouter-Title": "Connection Test"
        }
    )
    
    print(f"⏳ Testing connection to OpenRouter...")
    
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Say 'Hello, connection works!'"}],
            temperature=0.2,
            max_tokens=50,
            stream=False
        )
        print(f"✅ SUCCESS: {response.choices[0].message.content}")
        print(f"📊 Model: {response.model}")
        if response.usage:
            print(f"📊 Tokens used: {response.usage.total_tokens}")
    except Exception as e:
        error_msg = str(e)
        print(f"❌ FAILED: {type(e).__name__}: {error_msg}")
        
        if "401" in error_msg or "Unauthorized" in error_msg:
            print("\n🔧 TROUBLESHOOTING:")
            print("1. Check if your API key is valid at: https://openrouter.ai/keys")
            print("2. Make sure you have credits in your OpenRouter account")
            print("3. Try creating a new API key")
            print("4. Check if .env file is in the correct folder")
            print(f"   Current folder: {os.getcwd()}")
            print("5. Make sure .env file contains: OPENROUTER_API_KEY=sk-or-v1-...")
        elif "timeout" in error_msg.lower():
            print("\n🔧 Connection timeout. Check your internet/VPN.")
        elif "connection" in error_msg.lower():
            print("\n🔧 Connection error. Check your internet/VPN/Filtershekan.")

if __name__ == "__main__":
    print("🔬 OpenRouter Connection Test")
    print(f"📁 Working directory: {os.getcwd()}")
    print(f"📁 .env exists: {os.path.exists('.env')}")
    print()
    asyncio.run(test())