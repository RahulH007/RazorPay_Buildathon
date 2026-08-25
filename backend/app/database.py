"""
RecoverOS Database Module
SQLAlchemy engine, session factory, and declarative base.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

# SQLite needs check_same_thread=False for FastAPI async usage
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)


def configure_sqlite(target_engine) -> bool:
    """
    Apply SQLite pragmas needed for concurrent ledger appends.

    WAL lets readers run concurrently with a single writer, which is the right
    shape for this workload: the dashboard polls metrics constantly while a
    batch appends to the ledger.

    Deliberately NOT using a blanket ``BEGIN IMMEDIATE`` on every transaction.
    It would serialize read-only queries behind the write lock for no benefit,
    because chain correctness does not depend on transaction ordering — a fork
    requires two rows sharing a prev_hash, and the UNIQUE index rejects that
    regardless. A losing writer simply retries (see ledger.append_entry).
    ``busy_timeout`` absorbs the lock contention that remains.
    """
    if target_engine.dialect.name != "sqlite":
        return False

    @event.listens_for(target_engine, "connect")
    def _sqlite_on_connect(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            # No-ops for in-memory databases, which is fine.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return True


configure_sqlite(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
