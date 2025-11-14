from dotenv import load_dotenv
load_dotenv()

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database.db import init_models
from app.routers import web, portal, humblefax

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Check for HumbleFax credentials
HUMBLEFAX_ACCESS_KEY = os.getenv("HUMBLEFAX_ACCESS_KEY")
HUMBLEFAX_SECRET_KEY = os.getenv("HUMBLEFAX_SECRET_KEY")

if not HUMBLEFAX_ACCESS_KEY or not HUMBLEFAX_SECRET_KEY:
    logger.warning(
        "WARNING: HumbleFax credentials are missing. "
        "Please set HUMBLEFAX_ACCESS_KEY and HUMBLEFAX_SECRET_KEY. "
        "Outbound faxing will fail until credentials are configured."
    )

app = FastAPI(title="Veritas One API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(web.router, tags=["Web"])
app.include_router(portal.router, tags=["Portal"])
app.include_router(humblefax.router, prefix="/humblefax", tags=["HumbleFax Webhooks"])

@app.on_event("startup")
async def on_startup():
    await init_models()

@app.get("/healthz")
async def healthz():
    return {"ok": True}