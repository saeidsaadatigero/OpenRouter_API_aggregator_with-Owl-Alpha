# migrate.py

"""
Database Migration Tool
======================
Sync data between SQLite and PostgreSQL

Usage:
    python migrate.py sqlite-to-postgres
    python migrate.py postgres-to-sqlite
    python migrate.py check
"""

import sys
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SQLITE_URL = "sqlite:///./openrouter_studio.db"
POSTGRES_URL = "postgresql://owl_user:123456@localhost:5432/owl"


def get_session(url):
    """Get database session."""
    if "postgresql" in url:
        engine = create_engine(url, pool_pre_ping=True)
    else:
        engine = create_engine(url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    return Session(), engine


def create_tables(engine):
    """Create all tables."""
    from database import Base
    import models
    Base.metadata.create_all(bind=engine)


def get_table_columns(session, table):
    """Get column names for a table."""
    try:
        result = session.execute(text(f"SELECT * FROM {table} LIMIT 0"))
        return list(result.keys())
    except:
        return []


def get_counts(session, name):
    """Get row counts."""
    tables = ["chat_messages", "chat_sessions", "generation_history", "system_instructions"]
    counts = {}
    for t in tables:
        try:
            result = session.execute(text(f"SELECT COUNT(*) FROM {t}"))
            counts[t] = result.scalar()
        except:
            counts[t] = 0
    logger.info(f"[{name}] {counts}")
    return counts


def migrate_table(src_session, tgt_session, table, skip_errors=True):
    """Migrate single table."""
    try:
        src_cols = get_table_columns(src_session, table)
        tgt_cols = get_table_columns(tgt_session, table)
        common_cols = [c for c in src_cols if c in tgt_cols]
        
        if not common_cols:
            logger.warning(f"  {table}: No common columns!")
            return 0
        
        rows = src_session.execute(text(f"SELECT * FROM {table}")).fetchall()
        
        if not rows:
            logger.info(f"  {table}: 0 rows")
            return 0
        
        col_names = ", ".join(common_cols)
        placeholders = ", ".join([f":{c}" for c in common_cols])
        
        inserted = 0
        skipped = 0
        
        for row in rows:
            data = dict(zip(src_cols, row))
            filtered_data = {k: v for k, v in data.items() if k in common_cols}
            
            # Truncate long fields
            for key, value in filtered_data.items():
                if isinstance(value, str) and key == "prompt" and len(value) > 500:
                    filtered_data[key] = value[:497] + "..."
                elif isinstance(value, str) and key == "content" and len(value) > 100000:
                    filtered_data[key] = value[:99997] + "..."
            
            # Handle is_active for PostgreSQL
            if "is_active" in filtered_data:
                if filtered_data["is_active"] == 1 or filtered_data["is_active"] == "1":
                    filtered_data["is_active"] = True
                elif filtered_data["is_active"] == 0 or filtered_data["is_active"] == "0":
                    filtered_data["is_active"] = False
            
            try:
                tgt_session.execute(
                    text(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"),
                    filtered_data
                )
                inserted += 1
                
                if inserted % 20 == 0:
                    tgt_session.commit()
                    
            except Exception as e:
                skipped += 1
                if not skip_errors:
                    logger.warning(f"  Row {skipped} error: {str(e)[:80]}")
            
        tgt_session.commit()
        logger.info(f"  {table}: {inserted} migrated, {skipped} skipped")
        return inserted
        
    except Exception as e:
        logger.error(f"  Error: {e}")
        tgt_session.rollback()
        return 0


def migrate(source_url, target_url, source_name, target_name):
    """Migrate data."""
    logger.info("=" * 60)
    logger.info(f"Migrating: {source_name} → {target_name}")
    logger.info("=" * 60)
    
    src_session, src_engine = get_session(source_url)
    tgt_session, tgt_engine = get_session(target_url)
    
    try:
        create_tables(tgt_engine)
        
        # Get counts before
        logger.info("Source counts BEFORE:")
        src_counts_before = get_counts(src_session, source_name)
        
        # Clear target
        logger.info("Clearing target...")
        for t in ["chat_messages", "generation_history", "chat_sessions", "system_instructions"]:
            try:
                tgt_session.execute(text(f"DELETE FROM {t}"))
            except:
                pass
        tgt_session.commit()
        
        # Order matters for FK constraints!
        tables_order = ["chat_sessions", "chat_messages", "generation_history", "system_instructions"]
        
        logger.info("Migrating...")
        total = 0
        for table in tables_order:
            count = migrate_table(src_session, tgt_session, table)
            total += count
        
        logger.info(f"Total: {total} rows")
        
        # Verify
        logger.info("-" * 40)
        src_counts = get_counts(src_session, source_name)
        tgt_counts = get_counts(tgt_session, target_name)
        
        for t in tables_order:
            s = src_counts.get(t, 0)
            tg = tgt_counts.get(t, 0)
            status = "✅" if s == tg else "⚠️"
            logger.info(f"  {status} {t}: {source_name}={s}, {target_name}={tg}")
        
    except Exception as e:
        logger.error(f"Failed: {e}")
        tgt_session.rollback()
    finally:
        src_session.close()
        tgt_session.close()


def check():
    """Check connections."""
    logger.info("=" * 60)
    logger.info("Checking connections...")
    logger.info("=" * 60)
    
    try:
        s, _ = get_session(SQLITE_URL)
        v = s.execute(text("SELECT sqlite_version()")).scalar()
        get_counts(s, "SQLite")
        s.close()
        logger.info("✅ SQLite OK")
    except Exception as e:
        logger.error(f"❌ SQLite: {e}")
    
    try:
        s, _ = get_session(POSTGRES_URL)
        v = s.execute(text("SELECT version()")).scalar()
        get_counts(s, "PostgreSQL")
        s.close()
        logger.info("✅ PostgreSQL OK")
    except Exception as e:
        logger.error(f"❌ PostgreSQL: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1].lower()
    
    if cmd == "sqlite-to-postgres":
        migrate(SQLITE_URL, POSTGRES_URL, "SQLite", "PostgreSQL")
    elif cmd == "postgres-to-sqlite":
        migrate(POSTGRES_URL, SQLITE_URL, "PostgreSQL", "SQLite")
    elif cmd == "check":
        check()
    else:
        print(f"Unknown: {cmd}")
