from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from kabel.internal.common.config import settings

engine = None
database_url = settings.DATABASE_URL

if settings.DATABASE_URL.startswith("mysql"):
    engine = create_engine(
        database_url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        pool_use_lifo=True,
    )
else:
    # connect_args is needed only for SQLite. It's not needed for other databases
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False, bind=engine)

Base = declarative_base()


# create database tables
def init_tables() -> None:
    Base.metadata.create_all(bind=engine)


def begin_transaction(session: Session):
    """Begin a writable transaction after any SQLAlchemy 2.0 autobegin-only work."""
    if session.in_transaction():
        session.rollback()
    return session.begin()


def get_db() -> Generator:
    db = None
    try:
        db = SessionLocal()
        yield db
    finally:
        if db is not None:
            db.close()
