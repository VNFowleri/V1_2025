# backend/app/database/db.py
import os
import sys
import ssl
import certifi
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Declarative base used by all models
Base = declarative_base()

# Get DATABASE_URL from environment with better validation
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Validate DATABASE_URL if it's set
if DATABASE_URL:
    # Check if it's a PostgreSQL URL
    if DATABASE_URL.startswith("postgresql"):
        # Basic validation - ensure there's a hostname
        if "://" in DATABASE_URL:
            # Extract the part after ://
            url_parts = DATABASE_URL.split("://", 1)
            if len(url_parts) == 2:
                connection_part = url_parts[1]
                # Check if there's at least something after the protocol
                if not connection_part or connection_part.startswith("/") or connection_part.startswith("@"):
                    print("⚠️  WARNING: DATABASE_URL appears malformed (missing hostname)")
                    print(f"   DATABASE_URL: {DATABASE_URL}")
                    print("   Falling back to SQLite for development")
                    DATABASE_URL = ""
            else:
                print("⚠️  WARNING: DATABASE_URL is invalid")
                DATABASE_URL = ""
        else:
            print("⚠️  WARNING: DATABASE_URL is missing protocol")
            DATABASE_URL = ""

# If no valid DATABASE_URL, use SQLite
if not DATABASE_URL:
    DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
    print(f"✅ Using SQLite database: {DATABASE_URL}")
else:
    # Mask password in log output
    if "@" in DATABASE_URL:
        parts = DATABASE_URL.split("@")
        if "://" in parts[0]:
            proto_and_creds = parts[0].split("://")
            if len(proto_and_creds) == 2 and ":" in proto_and_creds[1]:
                masked = f"{proto_and_creds[0]}://****:****@{parts[1]}"
                print(f"✅ Using PostgreSQL database: {masked}")
            else:
                print(f"✅ Using database: {DATABASE_URL}")
        else:
            print(f"✅ Using database: {DATABASE_URL}")
    else:
        print(f"✅ Using database: {DATABASE_URL}")

# TLS for managed Postgres (e.g., Neon) via asyncpg
connect_args = {}
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connect_args["ssl"] = ssl_context

# Create async engine with error handling
try:
    engine = create_async_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args=connect_args,
        echo=False,  # Set to True for SQL debugging
    )
except Exception as e:
    print(f"❌ ERROR creating database engine: {e}", file=sys.stderr)
    print(f"   DATABASE_URL: {DATABASE_URL}", file=sys.stderr)
    raise

# Async session factory
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# Backward-compat alias; app.database.__init__ may expect this name
AsyncSessionLocal = SessionLocal

# --- Import models so metadata is registered for create_all ---
# Import only models that exist in your codebase
try:
    from app.models.patient import Patient  # noqa: F401, E402
    from app.models.fax_file import FaxFile  # noqa: F401, E402
    from app.models.provider import Provider  # noqa: F401, E402
    from app.models.consent import PatientConsent  # noqa: F401, E402
    # ProviderRequest is defined inside record_request.py, not separate
    from app.models.record_request import RecordRequest, ProviderRequest  # noqa: F401, E402

    print("✅ Models imported successfully")
except ImportError as e:
    print(f"⚠️  Warning: Some models could not be imported: {e}")
    print("   This is usually OK if you're still setting up the project")


async def init_models():
    """
    Create all tables in the database if they don't exist.
    Called once on app startup.
    """
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("✅ Database tables initialized successfully")
    except Exception as e:
        print(f"❌ ERROR initializing database tables: {e}", file=sys.stderr)
        print("\n🔍 Troubleshooting tips:", file=sys.stderr)
        print("   1. Check your DATABASE_URL environment variable", file=sys.stderr)
        print("   2. Ensure PostgreSQL is running (if using PostgreSQL)", file=sys.stderr)
        print("   3. Verify network connectivity to database server", file=sys.stderr)
        print(f"   4. Current DATABASE_URL: {DATABASE_URL}", file=sys.stderr)
        raise


async def get_db() -> AsyncSession:
    """
    Dependency to get a database session.
    Usage: def my_route(db: AsyncSession = Depends(get_db))
    """
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_async_session_context():
    """
    Context manager to get a new database session for background tasks.

    Usage in background tasks:
        async with get_async_session_context() as db:
            # Use db session here
            result = await db.execute(select(Model).where(...))
            await db.commit()

    This is needed because background tasks don't have access to the
    FastAPI dependency injection system, so we can't use Depends(get_db).

    Example:
        async def process_fax_background(fax_id: int):
            async with get_async_session_context() as db:
                fax = await db.get(FaxFile, fax_id)
                fax.status = "processed"
                await db.commit()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()