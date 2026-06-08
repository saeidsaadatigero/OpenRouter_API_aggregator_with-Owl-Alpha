# database.py

import logging
import subprocess
import sys
from decouple import config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# ── Database Engine Selection ───────────────────────
DB_ENGINE = config("DB_ENGINE", default="sqlite")

# SQLite Settings
SQLITE_PATH = config("SQLITE_PATH", default="./openrouter_studio.db")

# PostgreSQL Settings
POSTGRES_HOST = config("POSTGRES_HOST", default="localhost")
POSTGRES_PORT = config("POSTGRES_PORT", default="5432")
POSTGRES_USER = config("POSTGRES_USER", default="owl_user")
POSTGRES_PASSWORD = config("POSTGRES_PASSWORD", default="123456")
POSTGRES_DB = config("POSTGRES_DB", default="owl")

# Track if migration has been done this session
_migration_done = False


def get_database_url() -> str:
    """Get database URL based on selected engine."""
    if DB_ENGINE == "postgres":
        url = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
        logger.info(f"[DB] Using PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
        return url
    else:
        url = f"sqlite:///{SQLITE_PATH}"
        logger.info(f"[DB] Using SQLite: {SQLITE_PATH}")
        return url


def create_db_engine():
    """Create SQLAlchemy engine based on selected database."""
    url = get_database_url()
    
    if DB_ENGINE == "postgres":
        engine = create_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False
        )
    else:
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            echo=False
        )
    
    return engine


# ── Create Engine ───────────────────────────────────
engine = create_db_engine()

# ── Session Factory ─────────────────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── Base Class ──────────────────────────────────────
Base = declarative_base()


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def auto_sync_if_needed():
    """
    Auto-sync data between databases when switching.
    Called on startup to ensure data consistency.
    """
    global _migration_done
    
    if _migration_done:
        return
    
    _migration_done = True
    
    try:
        # Check current data counts
        with engine.connect() as conn:
            if DB_ENGINE == "postgres":
                # Check if PostgreSQL is empty but SQLite has data
                result = conn.execute(text("SELECT COUNT(*) FROM chat_sessions"))
                pg_count = result.scalar()
                
                if pg_count == 0:
                    # Try to sync from SQLite
                    logger.info("[AUTO-SYNC] PostgreSQL is empty, syncing from SQLite...")
                    sync_sqlite_to_postgres()
                else:
                    logger.info(f"[AUTO-SYNC] PostgreSQL has {pg_count} sessions, no sync needed")
            else:
                # Check if SQLite is empty but PostgreSQL has data
                result = conn.execute(text("SELECT COUNT(*) FROM chat_sessions"))
                sqlite_count = result.scalar()
                
                if sqlite_count == 0:
                    # Try to sync from PostgreSQL
                    logger.info("[AUTO-SYNC] SQLite is empty, syncing from PostgreSQL...")
                    sync_postgres_to_sqlite()
                else:
                    logger.info(f"[AUTO-SYNC] SQLite has {sqlite_count} sessions, no sync needed")
                    
    except Exception as e:
        logger.warning(f"[AUTO-SYNC] Sync check failed: {e}")


def sync_sqlite_to_postgres():
    """Sync data from SQLite to PostgreSQL."""
    try:
        sqlite_engine = create_engine(f"sqlite:///{SQLITE_PATH}", connect_args={"check_same_thread": False})
        pg_engine = create_engine(
            f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
            pool_pre_ping=True
        )
        
        sqlite_session = sessionmaker(bind=sqlite_engine)()
        pg_session = sessionmaker(bind=pg_engine)()
        
        # Import models
        import models
        Base.metadata.create_all(bind=pg_engine)
        
        # Clear PostgreSQL
        pg_session.execute(text("DELETE FROM chat_messages"))
        pg_session.execute(text("DELETE FROM chat_sessions"))
        pg_session.execute(text("DELETE FROM generation_history"))
        pg_session.execute(text("DELETE FROM system_instructions"))
        pg_session.commit()
        
        # Copy sessions
        sessions = sqlite_session.execute(text("SELECT * FROM chat_sessions")).fetchall()
        if sessions:
            cols = ["id", "title", "created_at", "updated_at"]
            for row in sessions:
                data = dict(zip(cols, row))
                pg_session.execute(
                    text("INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (:id, :title, :created_at, :updated_at)"),
                    data
                )
            pg_session.commit()
            logger.info(f"[AUTO-SYNC] {len(sessions)} sessions synced")
        
        # Copy messages
        messages = sqlite_session.execute(text("SELECT * FROM chat_messages")).fetchall()
        if messages:
            for row in messages:
                data = {
                    "id": row[0], "session_id": row[1], "role": row[2],
                    "content": row[3] if len(row[3]) < 100000 else row[3][:99997] + "...",
                    "created_at": row[4], "status": row[5]
                }
                try:
                    pg_session.execute(
                        text("INSERT INTO chat_messages (id, session_id, role, content, created_at, status) VALUES (:id, :session_id, :role, :content, :created_at, :status)"),
                        data
                    )
                except:
                    pass
            pg_session.commit()
            logger.info(f"[AUTO-SYNC] {len(messages)} messages synced")
        
        # Copy instructions
        instructions = sqlite_session.execute(text("SELECT * FROM system_instructions")).fetchall()
        if instructions:
            for row in instructions:
                is_active = True if row[3] == 1 else False
                data = {"id": row[0], "title": row[1], "content": row[2], "is_active": is_active, "created_at": row[4], "updated_at": row[5]}
                try:
                    pg_session.execute(
                        text("INSERT INTO system_instructions (id, title, content, is_active, created_at, updated_at) VALUES (:id, :title, :content, :is_active, :created_at, :updated_at)"),
                        data
                    )
                except:
                    pass
            pg_session.commit()
            logger.info(f"[AUTO-SYNC] {len(instructions)} instructions synced")
        
        sqlite_session.close()
        pg_session.close()
        logger.info("✅ [AUTO-SYNC] SQLite → PostgreSQL completed!")
        
    except Exception as e:
        logger.error(f"❌ [AUTO-SYNC] Failed: {e}")


def sync_postgres_to_sqlite():
    """Sync data from PostgreSQL to SQLite."""
    try:
        sqlite_engine = create_engine(f"sqlite:///{SQLITE_PATH}", connect_args={"check_same_thread": False})
        pg_engine = create_engine(
            f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
            pool_pre_ping=True
        )
        
        sqlite_session = sessionmaker(bind=sqlite_engine)()
        pg_session = sessionmaker(bind=pg_engine)()
        
        # Import models
        import models
        Base.metadata.create_all(bind=sqlite_engine)
        
        # Clear SQLite
        sqlite_session.execute(text("DELETE FROM chat_messages"))
        sqlite_session.execute(text("DELETE FROM chat_sessions"))
        sqlite_session.execute(text("DELETE FROM generation_history"))
        sqlite_session.execute(text("DELETE FROM system_instructions"))
        sqlite_session.commit()
        
        # Copy sessions
        sessions = pg_session.execute(text("SELECT * FROM chat_sessions")).fetchall()
        if sessions:
            for row in sessions:
                data = {"id": row[0], "title": row[1], "created_at": row[2], "updated_at": row[3]}
                sqlite_session.execute(
                    text("INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (:id, :title, :created_at, :updated_at)"),
                    data
                )
            sqlite_session.commit()
            logger.info(f"[AUTO-SYNC] {len(sessions)} sessions synced")
        
        # Copy messages
        messages = pg_session.execute(text("SELECT * FROM chat_messages")).fetchall()
        if messages:
            for row in messages:
                data = {
                    "id": row[0], "session_id": row[1], "role": row[2],
                    "content": row[3] if len(row[3]) < 100000 else row[3][:99997] + "...",
                    "created_at": row[4], "status": row[5]
                }
                try:
                    sqlite_session.execute(
                        text("INSERT INTO chat_messages (id, session_id, role, content, created_at, status) VALUES (:id, :session_id, :role, :content, :created_at, :status)"),
                        data
                    )
                except:
                    pass
            sqlite_session.commit()
            logger.info(f"[AUTO-SYNC] {len(messages)} messages synced")
        
        # Copy instructions
        instructions = pg_session.execute(text("SELECT * FROM system_instructions")).fetchall()
        if instructions:
            for row in instructions:
                is_active = 1 if row[3] else 0
                data = {"id": row[0], "title": row[1], "content": row[2], "is_active": is_active, "created_at": row[4], "updated_at": row[5]}
                try:
                    sqlite_session.execute(
                        text("INSERT INTO system_instructions (id, title, content, is_active, created_at, updated_at) VALUES (:id, :title, :content, :is_active, :created_at, :updated_at)"),
                        data
                    )
                except:
                    pass
            sqlite_session.commit()
            logger.info(f"[AUTO-SYNC] {len(instructions)} instructions synced")
        
        sqlite_session.close()
        pg_session.close()
        logger.info("✅ [AUTO-SYNC] PostgreSQL → SQLite completed!")
        
    except Exception as e:
        logger.error(f"❌ [AUTO-SYNC] Failed: {e}")


def init_db():
    """Initialize database tables."""
    logger.info(f"[DB] Initializing database (engine: {DB_ENGINE})...")
    
    # Import all models to register them
    import models
    
    Base.metadata.create_all(bind=engine)
    logger.info("[DB] Database tables created successfully.")
    
    # Auto-sync if needed
    auto_sync_if_needed()


def check_connection():
    """Check database connection."""
    try:
        with engine.connect() as conn:
            if DB_ENGINE == "postgres":
                result = conn.execute(text("SELECT version()"))
                version = result.scalar()
                result2 = conn.execute(text("SELECT COUNT(*) FROM chat_sessions"))
                count = result2.scalar()
                logger.info(f"[DB] PostgreSQL connected: {version[:50]}... | Sessions: {count}")
            else:
                result = conn.execute(text("SELECT sqlite_version()"))
                version = result.scalar()
                result2 = conn.execute(text("SELECT COUNT(*) FROM chat_sessions"))
                count = result2.scalar()
                logger.info(f"[DB] SQLite connected: v{version} | Sessions: {count}")
        return True
    except Exception as e:
        logger.error(f"[DB] Connection failed: {e}")
        return False
