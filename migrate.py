# migrate.py
import sqlite3

conn = sqlite3.connect('openrouter_studio.db')
conn.execute("ALTER TABLE chat_messages ADD COLUMN status VARCHAR(20) DEFAULT 'done'")
conn.commit()

cols = [row[1] for row in conn.execute('PRAGMA table_info(chat_messages)').fetchall()]
print('Columns:', cols)
conn.close()
print('Migration successful.')