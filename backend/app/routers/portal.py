"""
Updated Portal Router - v2.0

New Features:
- Endpoint to compile all patient records (not just per-request)
- Records ordered by encounter date
- Summary of available records
"""

import os
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.db import get_db
from app.models.patient import Patient
from app.models.record_request import RecordRequest
from app.models.fax_file import FaxFile
from app.services.medical_records_compiler import compile_all_patient_records, get_patient_records_summary

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
    res = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    rr_res = await db.execute(select(RecordRequest).where(RecordRequest.patient_id == patient.id))
    requests = rr_res.scalars().all()

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
        "records_summary": records_summary,  # NEW
        "active_request": active_request,
        "new_request_url": f"/search-providers/{patient.id}",
        "status_url": f"/status/{active_request.id}" if active_request else None
    })


@router.get("/portal/{patient_uuid}/download/{request_id}")
async def download_compiled(request: Request, patient_uuid: str, request_id: int, db: AsyncSession = Depends(get_db)):
    """
    Download compiled records for a specific request.

    This downloads only the records from a specific record request.
    """
    res = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    rr = await db.get(RecordRequest, request_id)
    if not rr or rr.patient_id != patient.id:
        raise HTTPException(status_code=404, detail="Record request not found")

    if not rr.compiled_pdf_path or not os.path.exists(rr.compiled_pdf_path):
        raise HTTPException(status_code=404, detail="Compiled PDF not available yet")

    return FileResponse(
        rr.compiled_pdf_path,
        filename=f"VeritasOne_Records_{patient.last_name}_{request_id}.pdf",
        media_type="application/pdf"
    )


@router.get("/portal/{patient_uuid}/compile-all")
async def compile_all_records(request: Request, patient_uuid: str, db: AsyncSession = Depends(get_db)):
    """
    Compile ALL medical records for a patient into a single PDF.

    NEW ENDPOINT: Compiles all faxes for the patient, ordered by encounter date.
    This is different from per-request compilation which only includes records
    from a specific request.

    The compiled PDF will have records ordered chronologically by the date
    medical services were provided (encounter date), not by request date.
    """
    res = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Check if patient has any records
    faxes_res = await db.execute(select(FaxFile).where(FaxFile.patient_id == patient.id))
    faxes = faxes_res.scalars().all()

    if not faxes:
        raise HTTPException(
            status_code=404,
            detail="No medical records found for this patient"
        )

    # Compile all records
    compiled_path = await compile_all_patient_records(
        patient_id=patient.id,
        db=db,
        output_filename=f"VeritasOne_AllRecords_{patient.last_name}_{patient_uuid}.pdf"
    )

    if not compiled_path:
        raise HTTPException(
            status_code=500,
            detail="Failed to compile medical records"
        )

    # Return the compiled PDF
    return FileResponse(
        compiled_path,
        filename=f"VeritasOne_AllRecords_{patient.last_name}.pdf",
        media_type="application/pdf"
    )


@router.get("/portal/{patient_uuid}/fax/{fax_id}")
async def download_fax_pdf(request: Request, patient_uuid: str, fax_id: int, db: AsyncSession = Depends(get_db)):
    """
    Download a specific fax file.

    This downloads an individual fax (not compiled).
    """
    res = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    fax = await db.get(FaxFile, fax_id)
    if not fax or fax.patient_id != patient.id:
        raise HTTPException(status_code=404, detail="Fax not found")

    if not fax.file_path or not os.path.exists(fax.file_path):
        raise HTTPException(status_code=404, detail="Fax PDF not present")

    return FileResponse(fax.file_path, filename=f"fax_{fax.id}.pdf", media_type="application/pdf")


@router.get("/portal/{patient_uuid}/records-summary")
async def get_records_summary(request: Request, patient_uuid: str, db: AsyncSession = Depends(get_db)):
    """
    Get a summary of all records for a patient.

    API endpoint for AJAX requests to show record details.
    """
    res = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    summary = await get_patient_records_summary(patient.id, db)

    return {
        "patient_id": patient.id,
        "patient_name": f"{patient.first_name} {patient.last_name}",
        "summary": summary
    }