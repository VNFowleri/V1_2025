from dotenv import load_dotenv
load_dotenv()

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database.db import init_models
from app.routers import web, portal, ifax

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IFAX_ACCESS_TOKEN = os.getenv("IFAX_ACCESS_TOKEN")
if not IFAX_ACCESS_TOKEN:
    logger.warning("WARNING: IFAX_ACCESS_TOKEN is missing. Outbound faxing will fail until it is set.")

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
app.include_router(ifax.router, prefix="/ifax", tags=["IFax Webhooks"])

@app.on_event("startup")
async def on_startup():
    await init_models()

@app.get("/healthz")
async def healthz():
    return {"ok": True}