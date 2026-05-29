# fix_db.py
import sqlite3

conn = sqlite3.connect('openrouter_studio.db')

r1 = conn.execute("UPDATE chat_messages SET status='done' WHERE role='user'").rowcount
r2 = conn.execute("UPDATE chat_messages SET status='error', content='[Interrupted]' WHERE status='pending' AND content=''").rowcount

conn.commit()

print(f"Fixed user messages: {r1}")
print(f"Fixed orphan pending: {r2}")

rows = conn.execute("SELECT id, role, status, content FROM chat_messages ORDER BY id DESC LIMIT 10").fetchall()
print("\nLast 10 messages:")
for row in rows:
    print(f"  id={row[0]} role={row[1]} status={row[2]} content='{str(row[3])[:40]}'")

conn.close()