# backend/app/database/db.py
import os
import ssl
import certifi
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Declarative base used by all models
Base = declarative_base()

# Prefer Postgres if provided; otherwise fall back to local SQLite for dev.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

# TLS for managed Postgres (e.g., Neon) via asyncpg
connect_args = {}
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connect_args["ssl"] = ssl_context

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)

# Async session factory
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# Backward-compat alias; app.database.__init__ may expect this name
AsyncSessionLocal = SessionLocal

# --- Import models so metadata is registered for create_all ---
# (Only import models that actually exist in app/models)
from app.models.patient import Patient          # noqa: F401
from app.models.fax_file import FaxFile         # noqa: F401
from app.models.provider import Provider        # noqa: F401
from app.models.consent import PatientConsent   # noqa: F401
from app.models.record_request import RecordRequest, ProviderRequest  # noqa: F401
# --------------------------------------------------------------

async def init_models():
    """Create tables if they don't exist (called on app startup)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# FastAPI dependency
async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()