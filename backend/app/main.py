"""
Veritas One - FastAPI Main Application

Medical records collection automation platform with:
- Patient registration and consent
- Provider search and selection
- Automated fax transmission via HumbleFax
- Incoming fax processing with OCR
- Patient portal for records access
"""

import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Import routers
from app.routers import web, portal, humblefax

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    """
    # Startup
    logger.info("🚀 Starting Veritas One application...")
    logger.info("✅ Application started successfully")

    yield

    # Shutdown
    logger.info("👋 Shutting down Veritas One application...")


# Create FastAPI app
app = FastAPI(
    title="Veritas One",
    description="Medical Records Collection Automation",
    version="3.1.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(web.router, tags=["Web"])
app.include_router(portal.router, tags=["Portal"])
app.include_router(humblefax.router, tags=["HumbleFax"])

logger.info("📡 Registered routers: web, portal, humblefax")


@app.get("/healthz")
async def health_check():
    """
    Health check endpoint.
    """
    return {
        "status": "healthy",
        "version": "3.1.0",
        "service": "veritas-one"
    }


@app.get("/")
async def root():
    """
    Root endpoint - redirects to main landing page.
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/", status_code=307)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )