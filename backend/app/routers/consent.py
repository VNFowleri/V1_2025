# app/routers/consent.py - v2.0
"""
Consent Router - Enhanced HIPAA-Compliant Authorization

Handles the patient consent and authorization form with:
- Full HIPAA-compliant release form display
- Signature capture
- Initial capture for sensitive categories
- Professional PDF generation for both release form and fax cover sheets

Version 2.0: Full template implementation with checkboxes and initials
"""

import os
import base64
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import get_db
from app.models import Patient, PatientConsent
from app.services.pdf_ops import generate_release_pdf

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/{patient_id}")
async def consent_form(
        request: Request,
        patient_id: int,
        db: AsyncSession = Depends(get_db)
):
    """
    Display the full HIPAA authorization form for patient signature.

    Shows complete release authorization with:
    - Patient information
    - Record types selection
    - Sensitive information initials
    - Signature capture
    """
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return templates.TemplateResponse(
        "consent.html",
        {
            "request": request,
            "patient": patient
        }
    )


@router.post("/{patient_id}")
async def submit_consent(
        request: Request,
        patient_id: int,
        signature_data_url: str = Form(...),
        # Initials for sensitive categories
        initial_hiv_value: str = Form(""),
        initial_genetic_value: str = Form(""),
        initial_sud_value: str = Form(""),
        initial_mental_value: str = Form(""),
        initial_psychotherapy_value: str = Form(""),
        db: AsyncSession = Depends(get_db),
):
    """
    Process the signed consent form and generate professional PDF documents.

    This endpoint:
    1. Validates the patient exists
    2. Saves the signature image
    3. Generates a professional HIPAA-compliant release PDF
    4. Creates a PatientConsent database record
    5. Redirects to provider search

    The generated PDF will be used as an attachment for all fax requests.
    """
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Create directories for storage
    sig_dir = "storage/signatures"
    os.makedirs(sig_dir, exist_ok=True)

    release_dir = "storage/releases"
    os.makedirs(release_dir, exist_ok=True)

    # Save signature image
    try:
        b64_data = signature_data_url.split(",")[-1]
        sig_bytes = base64.b64decode(b64_data)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid signature data: {e}"
        )

    sig_path = os.path.join(sig_dir, f"sig_{patient.id}.png")
    with open(sig_path, "wb") as f:
        f.write(sig_bytes)

    # Generate professional release PDF
    release_path = os.path.join(release_dir, f"release_patient_{patient.id}.pdf")
    patient_name = f"{patient.first_name} {patient.last_name}"
    dob_str = patient.date_of_birth.isoformat() if patient.date_of_birth else ""

    generate_release_pdf(
        output_path=release_path,
        patient_name=patient_name,
        dob=dob_str,
        email=patient.email or "",
        phone=patient.phone or "",
        signature_image_path=sig_path,
        # Pass initials for sensitive categories
        initial_hiv=initial_hiv_value,
        initial_genetic=initial_genetic_value,
        initial_sud=initial_sud_value,
        initial_mental=initial_mental_value,
        initial_psychotherapy=initial_psychotherapy_value,
        # Default to "all records" checked
        records_all=True,
    )

    # Create PatientConsent record
    consent_obj = PatientConsent(
        patient_id=patient.id,
        release_text_version="v2.0",  # Updated version
        consent_pdf_path=release_path,
        signature_image_path=sig_path,
        signed_at=datetime.utcnow(),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")
    )
    db.add(consent_obj)
    await db.commit()

    # Redirect to provider search
    return RedirectResponse(
        url=f"/search-providers/{patient.id}",
        status_code=303
    )