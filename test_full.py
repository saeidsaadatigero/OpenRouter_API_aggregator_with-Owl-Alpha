# test_full.py
import asyncio
import sqlite3
import httpx
import time
import sys
from decouple import config as dc

BASE_URL = "http://127.0.0.1:8000"
DB_PATH  = "openrouter_studio.db"

G  = "\033[92m✓\033[0m"
R  = "\033[91m✗\033[0m"
Y  = "\033[93m⚠\033[0m"
I  = "\033[94m→\033[0m"
B  = "\033[1;36m"
E  = "\033[0m"
P  = "\033[1;35m"

results = {"pass": 0, "fail": 0, "warn": 0}

def section(title):
    print(f"\n{P}{'─'*55}{E}")
    print(f"{P}  {title}{E}")
    print(f"{P}{'─'*55}{E}")

def ok(label, detail=""):
    results["pass"] += 1
    print(f"  {G} {label}" + (f"  \033[90m({detail})\033[0m" if detail else ""))

def fail(label, detail=""):
    results["fail"] += 1
    print(f"  {R} {label}" + (f"  \033[90m({detail})\033[0m" if detail else ""))

def warn(label, detail=""):
    results["warn"] += 1
    print(f"  {Y} {label}" + (f"  \033[90m({detail})\033[0m" if detail else ""))

def check(label, condition, detail="", critical=False):
    if condition:
        ok(label, detail)
    else:
        fail(label, detail) if critical else warn(label, detail)
    return condition

# ══════════════════════════════════════════════════════
# 1. ENV
# ══════════════════════════════════════════════════════
def test_env():
    section("1. ENVIRONMENT CONFIG")
    api_key      = dc("OPENROUTER_API_KEY", default="")
    max_prompt   = dc("MAX_PROMPT_LENGTH",  default="0", cast=int)
    max_context  = dc("MAX_CONTEXT_TOKENS", default="0", cast=int)

    check("OPENROUTER_API_KEY is set",       bool(api_key),
          f"...{api_key[-8:]}" if api_key else "MISSING", critical=True)
    check("API key format: sk-or-v1-",       api_key.startswith("sk-or-v1-"),
          f"prefix={api_key[:12]}", critical=True)
    check("API key length >= 60 chars",      len(api_key) >= 60,
          f"len={len(api_key)}")
    check("MAX_PROMPT_LENGTH >= 100000",     max_prompt >= 100000,
          f"value={max_prompt} ← fix .env", critical=True)
    check("MAX_CONTEXT_TOKENS set",          max_context > 0,
          f"value={max_context}")
    return api_key

# ══════════════════════════════════════════════════════
# 2. DATABASE
# ══════════════════════════════════════════════════════
def test_database():
    section("2. DATABASE SCHEMA")
    try:
        conn = sqlite3.connect(DB_PATH)

        s_cols = [r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()]
        check("chat_sessions table exists",        bool(s_cols), str(s_cols), critical=True)
        for col in ["id","title","created_at","updated_at"]:
            check(f"  chat_sessions.{col}",        col in s_cols, critical=True)

        m_cols = [r[1] for r in conn.execute("PRAGMA table_info(chat_messages)").fetchall()]
        check("chat_messages table exists",        bool(m_cols), str(m_cols), critical=True)
        for col in ["id","session_id","role","content","created_at"]:
            check(f"  chat_messages.{col}",        col in m_cols, critical=True)
        check("  chat_messages.status ← CRITICAL", "status" in m_cols,
              "run migrate.py!", critical=True)

        # orphan pending messages
        pending = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE status='pending'"
        ).fetchone()[0]
        if pending > 0:
            warn(f"Found {pending} orphan pending messages in DB",
                 "these will cause blank UI on load")
        else:
            ok("No orphan pending messages")

        conn.close()
    except Exception as e:
        fail(f"DB error: {e}", critical=True)

# ══════════════════════════════════════════════════════
# 3. OPENROUTER API DIRECT
# ══════════════════════════════════════════════════════
def test_openrouter_direct(api_key: str):
    section("3. OPENROUTER API — DIRECT CALL")
    if not api_key:
        warn("Skipped — no API key")
        return False

    MODELS_TO_TRY = [
        "deepseek/deepseek-chat",
        "openai/gpt-4o-mini",
        "anthropic/claude-3-haiku",
        "mistralai/mistral-7b-instruct",
    ]

    async def _test(model):
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            default_headers={"HTTP-Referer": "https://localhost:8000"}
        )
        try:
            r = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "reply with word OK only"}],
                max_tokens=5,
                timeout=15
            )
            return r.choices[0].message.content.strip(), None
        except Exception as e:
            return None, str(e)

    working_model = None
    for model in MODELS_TO_TRY:
        content, err = asyncio.run(_test(model))
        if content:
            ok(f"Model works: {model}", f"response='{content}'")
            working_model = model
            break
        else:
            warn(f"Model failed: {model}", err[:80] if err else "unknown")

    if not working_model:
        fail("No working model found — check API key and credits", critical=True)
        print(f"\n  {Y} Current model in openrouter_service.py: 'openrouter/owl-alpha'")
        print(f"  {Y} This model does NOT exist. Change to: 'deepseek/deepseek-chat'")
    else:
        print(f"\n  {I} \033[92mSet this in openrouter_service.py:\033[0m")
        print(f"     model_name: str = \"{working_model}\"")

    return working_model

# ══════════════════════════════════════════════════════
# 4. SERVER HEALTH
# ══════════════════════════════════════════════════════
def test_server():
    section("4. SERVER HEALTH")
    try:
        r = httpx.get(f"{BASE_URL}/", timeout=5)
        check("GET / → 200",          r.status_code == 200, f"status={r.status_code}", critical=True)
        check("Response is HTML",     "text/html" in r.headers.get("content-type",""))
        return True
    except httpx.ConnectError:
        fail(f"Server not running at {BASE_URL} — run: uvicorn main:app --reload", critical=True)
        return False

# ══════════════════════════════════════════════════════
# 5. SESSION CRUD
# ══════════════════════════════════════════════════════
def test_session_crud():
    section("5. SESSION CRUD")
    sid = None
    try:
        r = httpx.post(f"{BASE_URL}/api/chat/new", timeout=5)
        check("POST /new → 200",      r.status_code == 200, critical=True)
        sid = r.json().get("session_id")
        check("Has session_id",       bool(sid), str(sid), critical=True)
        print(f"  {I} session_id={sid}")

        r2 = httpx.get(f"{BASE_URL}/chat/{sid}", timeout=5)
        check(f"GET /chat/{sid} → 200", r2.status_code == 200)

        r3 = httpx.get(f"{BASE_URL}/api/chat/{sid}/messages", timeout=5)
        check("GET messages → 200",   r3.status_code == 200)
        msgs = r3.json()
        check("Returns list",         isinstance(msgs, list))
        check("Empty initially",      len(msgs) == 0, f"count={len(msgs)}")

        # check status field in response
        if msgs:
            check("Messages have status field", "status" in msgs[0], str(msgs[0]))

        r4 = httpx.post(f"{BASE_URL}/api/chat/{sid}/rename",
                         json={"title": "Test Renamed"}, timeout=5)
        check("POST rename → 200",    r4.status_code == 200, f"status={r4.status_code}")

        r5 = httpx.post(f"{BASE_URL}/api/chat/{sid}/delete", timeout=5)
        check("POST delete → 200",    r5.status_code == 200)

    except Exception as e:
        fail(f"Session CRUD error: {e}")
    return sid

# ══════════════════════════════════════════════════════
# 6. SEND PAYLOAD VALIDATION
# ══════════════════════════════════════════════════════
def test_payload_validation():
    section("6. SEND ENDPOINT — PAYLOAD VALIDATION")
    try:
        sid = httpx.post(f"{BASE_URL}/api/chat/new", timeout=5).json()["session_id"]

        # empty → 422
        r = httpx.post(f"{BASE_URL}/api/chat/{sid}/send",
                        json={"prompt": ""}, timeout=5)
        check("Empty prompt → 422",       r.status_code == 422, f"got {r.status_code}")

        # missing key → 422
        r = httpx.post(f"{BASE_URL}/api/chat/{sid}/send",
                        json={}, timeout=5)
        check("Missing prompt → 422",     r.status_code == 422, f"got {r.status_code}")

        # form data → 422
        r = httpx.post(f"{BASE_URL}/api/chat/{sid}/send",
                        data={"prompt": "test"}, timeout=5)
        check("Form data → 422",          r.status_code == 422, f"got {r.status_code}")

        # 50k prompt → should be 200 not 422
        r = httpx.post(f"{BASE_URL}/api/chat/{sid}/send",
                        json={"prompt": "x" * 50000}, timeout=10)
        check("50k prompt → 200 (not 422)",
              r.status_code == 200, f"got {r.status_code} ← if 422, ChatSendPayload.max_length is still 10000")

        # valid prompt
        r = httpx.post(f"{BASE_URL}/api/chat/{sid}/send",
                        json={"prompt": "say hello"}, timeout=15)
        check("Valid prompt → 200",       r.status_code == 200,
              f"got {r.status_code}", critical=True)

        if r.status_code == 200:
            data = r.json()
            check("Has 'status' field",   "status" in data, str(data))
            check("Has 'message_id'",     "message_id" in data, str(data))
            print(f"  {I} Backend response: status={data.get('status')}, message_id={data.get('message_id')}")

            # cleanup
            httpx.post(f"{BASE_URL}/api/chat/{sid}/delete", timeout=5)
            return data.get("message_id")

    except Exception as e:
        fail(f"Payload validation error: {e}")
    return None

# ══════════════════════════════════════════════════════
# 7. POLLING
# ══════════════════════════════════════════════════════
def test_polling(message_id):
    section("7. BACKGROUND TASK POLLING")
    if not message_id:
        warn("Skipped — no message_id from previous test")
        return

    try:
        r = httpx.get(f"{BASE_URL}/api/message/{message_id}/status", timeout=5)
        check("GET /status → 200",    r.status_code == 200, critical=True)
        data = r.json()
        check("Has 'status' field",   "status" in data, str(data))
        check("Status is valid",      data.get("status") in
              ("pending","processing","done","error"), f"got={data.get('status')}")
        print(f"  {I} Initial status: {data.get('status')}")

        # poll up to 90s
        print(f"  {I} Waiting for completion (max 90s)...")
        final = None
        for i in range(45):
            time.sleep(2)
            r2 = httpx.get(f"{BASE_URL}/api/message/{message_id}/status", timeout=5)
            d  = r2.json()
            st = d.get("status")
            print(f"  {I} [{(i+1)*2}s] status={st}")
            if st in ("done", "error"):
                final = st
                content = d.get("content", "")
                break

        check("Task reached done/error", final in ("done","error"),
              f"final={final}", critical=True)
        if final == "done":
            check("Content not empty",    bool(content), f"len={len(content)}")
            print(f"  {I} Preview: {content[:100]}...")
        elif final == "error":
            print(f"  {Y} Error content: {content[:200]}")
            print(f"\n  {Y} MODEL IS WRONG. Change 'openrouter/owl-alpha' → 'deepseek/deepseek-chat'")
            print(f"     File: services/openrouter_service.py  Line: __init__  param: model_name")

        # 404 test
        r3 = httpx.get(f"{BASE_URL}/api/message/999999/status", timeout=5)
        check("Nonexistent ID → 404", r3.status_code == 404, f"got={r3.status_code}")

    except Exception as e:
        fail(f"Polling error: {e}")

# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{B}{'═'*55}{E}")
    print(f"{B}  OWL STUDIO — COMPREHENSIVE DIAGNOSTIC v2{E}")
    print(f"{B}{'═'*55}{E}")

    api_key     = test_env()
    test_database()
    working_model = test_openrouter_direct(api_key)
    server_ok   = test_server()

    if server_ok:
        test_session_crud()
        message_id = test_payload_validation()
        test_polling(message_id)

    print(f"\n{B}{'═'*55}{E}")
    print(f"  {G} PASS: {results['pass']}   {R} FAIL: {results['fail']}   {Y} WARN: {results['warn']}")
    print(f"{B}{'═'*55}{E}\n")

    if results["fail"] > 0:
        print(f"  {R} Critical issues found — fix FAILs first\n")
        if working_model:
            print(f"  {Y} ACTION REQUIRED — in services/openrouter_service.py change:")
            print(f"     model_name: str = \"openrouter/owl-alpha\"")
            print(f"  → model_name: str = \"{working_model}\"\n")
        sys.exit(1)
    else:
        print(f"  {G} All checks passed!\n")