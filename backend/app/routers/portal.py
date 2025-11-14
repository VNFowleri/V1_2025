"""
Updated Portal Router - v2.0 - FIXED VERSION

New Features:
- Endpoint to compile all patient records (not just per-request)
- Records ordered by encounter date
- Summary of available records
- FIXED: Eager loading for relationships
- FIXED: Router initialization
"""

import os
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload  # <-- CRITICAL: Add this import

from app.database.db import get_db
from app.models.patient import Patient
from app.models.record_request import RecordRequest
from app.models.fax_file import FaxFile
from app.services.medical_records_compiler import compile_all_patient_records, get_patient_records_summary

# ✅ CRITICAL: This line MUST come BEFORE any @router decorators
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/portal/{patient_uuid}")
async def portal_home(request: Request, patient_uuid: str, db: AsyncSession = Depends(get_db)):
    """
    Patient portal home page.

    Shows:
    - Per-request compiled records
    - Individual faxes received
    - Button to compile ALL records
    """
    # Get patient
    res = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # ✅ FIXED: Eagerly load provider_requests relationship to avoid greenlet error
    rr_res = await db.execute(
        select(RecordRequest)
        .where(RecordRequest.patient_id == patient.id)
        .options(selectinload(RecordRequest.provider_requests))  # <-- CRITICAL FIX
    )
    requests = rr_res.scalars().all()

    # Get faxes
    faxes_res = await db.execute(select(FaxFile).where(FaxFile.patient_id == patient.id))
    faxes = faxes_res.scalars().all()

    # Get summary of all records for display
    records_summary = await get_patient_records_summary(patient.id, db)

    # Find active request to show status link (exclude cancelled)
    active_request = None
    for req in requests:
        if req.status in ["pending", "in_progress"]:
            active_request = req
            break

    return templates.TemplateResponse("portal.html", {
        "request": request,
        "patient": patient,
        "requests": requests,
        "faxes": faxes,
        "records_summary": records_summary,
        "active_request": active_request,
    })


@router.post("/portal/{patient_uuid}/compile-all")
async def compile_all_records(
    patient_uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Compile ALL patient records into a single PDF.
    Not tied to any specific request.
    """
    # Get patient
    res = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Compile all records
    compiled_path = await compile_all_patient_records(patient.id, db)

    if not compiled_path or not os.path.exists(compiled_path):
        raise HTTPException(status_code=500, detail="Failed to compile records")

    # Return the compiled PDF
    return FileResponse(
        path=compiled_path,
        media_type="application/pdf",
        filename=f"{patient.first_name}_{patient.last_name}_all_records.pdf"
    )


@router.get("/portal/{patient_uuid}/download-compiled/{request_id}")
async def download_compiled(
    patient_uuid: str,
    request_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Download a previously compiled PDF for a specific request.
    """
    # Get patient
    res = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Get request
    # ✅ Add eager loading if this passes to template
    rr_res = await db.execute(
        select(RecordRequest)
        .where(RecordRequest.id == request_id, RecordRequest.patient_id == patient.id)
    )
    record_request = rr_res.scalars().first()

    if not record_request:
        raise HTTPException(status_code=404, detail="Request not found")

    if not record_request.compiled_pdf_path or not os.path.exists(record_request.compiled_pdf_path):
        raise HTTPException(status_code=404, detail="Compiled PDF not found")

    return FileResponse(
        path=record_request.compiled_pdf_path,
        media_type="application/pdf",
        filename=f"{patient.first_name}_{patient.last_name}_request_{request_id}.pdf"
    )