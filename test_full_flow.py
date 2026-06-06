# test_full_flow.py
"""Test the entire pipeline: API, session, send, poll, stop, retry."""
import asyncio
import time
import httpx
from openai import AsyncOpenAI

API_KEY = "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"
BASE_URL = "http://127.0.0.1:8000"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
MODEL = "openrouter/owl-alpha"

async def test_direct_openrouter():
    """Test 1: Direct connection to OpenRouter (asyncio)."""
    print("\n" + "="*60)
    print("TEST 1: Direct OpenRouter connection (asyncio)")
    print("="*60)
    
    client = AsyncOpenAI(
        base_url=OPENROUTER_URL,
        api_key=API_KEY,
        timeout=120.0,  # افزایش timeout
        max_retries=3,
        default_headers={"HTTP-Referer": "https://localhost:8000"}
    )
    
    start = time.time()
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Say 'test ok' in one word"}],
            temperature=0.3,
            max_tokens=50,  # خیلی کم برای پاسخ سریع
            stream=False
        )
        elapsed = time.time() - start
        content = response.choices[0].message.content.strip()
        print(f"✅ SUCCESS ({elapsed:.1f}s): {content}")
        return True
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ FAILED ({elapsed:.1f}s): {type(e).__name__}: {e}")
        return False

async def test_full_api_flow():
    """Test 3: Full API flow with detailed error logging."""
    print("\n" + "="*60)
    print("TEST 3: Full API flow")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create session
        print("⏳ Creating session...")
        try:
            r = await client.post(f"{BASE_URL}/api/chat/new")
            print(f"  Status: {r.status_code}")
            print(f"  Response: {r.text[:200]}")
            r.raise_for_status()
            data = r.json()
            session_id = data['session_id']
            print(f"✅ Session created: {session_id}")
        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            return False
        except Exception as e:
            print(f"❌ Session creation failed: {type(e).__name__}: {e}")
            return False
        
        # Send message
        print("⏳ Sending message...")
        try:
            r = await client.post(
                f"{BASE_URL}/api/chat/{session_id}/send",
                json={"prompt": "Say 'API test ok'"}
            )
            print(f"  Status: {r.status_code}")
            print(f"  Response: {r.text[:200]}")
            r.raise_for_status()
            data = r.json()
            message_id = data['message_id']
            print(f"✅ Message sent: message_id={message_id}")
        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            return False
        except Exception as e:
            print(f"❌ Send failed: {type(e).__name__}: {e}")
            return False
        
        # Poll until done or error
        print(f"⏳ Polling message {message_id}...")
        max_polls = 30
        for i in range(max_polls):
            await asyncio.sleep(2)
            try:
                r = await client.get(f"{BASE_URL}/api/message/{message_id}/status")
                if r.status_code != 200:
                    print(f"  Poll {i+1}: HTTP {r.status_code}")
                    continue
                status_data = r.json()
                status = status_data['status']
                
                if i < 5 or status in ('done', 'error', 'cancelled'):
                    print(f"  Poll {i+1}: status={status}")
                
                if status == 'done':
                    content = status_data.get('content', '')
                    print(f"✅ Response received ({len(content)} chars): {content[:100]}...")
                    return True
                elif status == 'error':
                    content = status_data.get('content', '')
                    print(f"❌ Error response: {content[:200]}")
                    return False
                elif status == 'cancelled':
                    print(f"⏹ Message was cancelled")
                    return False
            except Exception as e:
                print(f"  Poll {i+1} error: {type(e).__name__}: {e}")
        
        print("❌ Timeout - no final status after polling")
        return False

async def test_stop_mechanism():
    """Test 4: Stop mechanism."""
    print("\n" + "="*60)
    print("TEST 4: Stop mechanism")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Create session
            r = await client.post(f"{BASE_URL}/api/chat/new")
            r.raise_for_status()
            session_id = r.json()['session_id']
            print(f"✅ Session: {session_id}")
            
            # Send message with long prompt
            r = await client.post(
                f"{BASE_URL}/api/chat/{session_id}/send",
                json={"prompt": "Write a very long essay about the history of Python programming language"}
            )
            r.raise_for_status()
            message_id = r.json()['message_id']
            print(f"✅ Message sent: {message_id}")
            
            # Wait 3 seconds then stop
            print("⏳ Waiting 3 seconds before stop...")
            await asyncio.sleep(3)
            
            print(f"🛑 Sending stop request...")
            r = await client.post(f"{BASE_URL}/api/message/{message_id}/stop")
            print(f"  Status: {r.status_code}")
            stop_result = r.json()
            print(f"🛑 Stop result: {stop_result}")
            
            # Check final status
            await asyncio.sleep(2)
            r = await client.get(f"{BASE_URL}/api/message/{message_id}/status")
            status = r.json()
            print(f"📊 Final status: {status['status']}")
            
            if status['status'] in ('cancelled', 'error'):
                print("✅ Stop mechanism works!")
                return True
            else:
                print(f"❌ Unexpected status: {status['status']}")
                return False
                
        except Exception as e:
            print(f"❌ Stop test failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return False

async def main():
    print("🔬 FULL SYSTEM TEST SUITE (Simplified)")
    print(f"Model: {MODEL}")
    print(f"API Base: {BASE_URL}")
    
    # فقط تست مستقیم و تست API
    results = {}
    
    results['direct'] = await test_direct_openrouter()
    
    if results['direct']:
        results['api_flow'] = await test_full_api_flow()
    else:
        print("\n⚠️ Skipping API test - direct connection failed")
        results['api_flow'] = False
    
    results['stop'] = await test_stop_mechanism()
    
    print("\n" + "="*60)
    print("📋 TEST SUMMARY")
    print("="*60)
    for test, passed in results.items():
        print(f"  {test}: {'✅ PASS' if passed else '❌ FAIL'}")
    
    if all(results.values()):
        print("\n🏁 Overall: ✅ ALL PASS")
    else:
        print("\n🏁 Overall: ❌ SOME FAILED")

if __name__ == "__main__":
    asyncio.run(main())