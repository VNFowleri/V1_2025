# app/routers/web.py - v2.0
# Enhanced with improved hospital search, medical records fax discovery, and professional consent forms

import os
import json
import base64
import logging
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.models.patient import Patient
from app.models.consent import PatientConsent
from app.models.record_request import RecordRequest, ProviderRequest
from app.models.provider import Provider
from app.services.pdf_ops import generate_release_pdf, write_cover_sheet

# Import enhanced hospital search (v2.0)
from app.services.hospital_directory import (
    search_hospitals,
    search_hospital_by_name,
    validate_fax_number,
    format_fax_number
)

from app.services.auth_service import (
    generate_magic_link,
    verify_magic_link,
    send_magic_link_email
)

from app.services.ifax_service import send_fax

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
log = logging.getLogger(__name__)

CONSENT_TEXT = """I authorize the release of my complete medical record, including but not limited to physician notes,
diagnoses, medications, laboratory results, imaging, and billing records, to myself (patient access).
This authorization is voluntary and may be revoked in writing at any time except to the extent that action
has already been taken. This authorization will expire 180 days from the date of signature.
"""


# -------------------------
# Helper Functions
# -------------------------
def get_patient_from_session(patient_uuid: str, db: AsyncSession):
    """Get patient from session UUID."""
    return patient_uuid


# -------------------------
# Home / Landing
# -------------------------
@router.get("/", response_class=HTMLResponse)
async def index(
        request: Request,
        patient_uuid: str = Cookie(None),
        db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    """Landing page - or redirect to status if logged in with active request."""

    if patient_uuid:
        result = await db.execute(select(Patient).where(Patient.uuid == patient_uuid))
        patient = result.scalars().first()

        if patient:
            req_result = await db.execute(
                select(RecordRequest)
                .where(RecordRequest.patient_id == patient.id)
                .where(RecordRequest.status.in_(["pending", "in_progress"]))
                .order_by(RecordRequest.created_at.desc())
            )
            active_request = req_result.scalars().first()

            if active_request:
                return RedirectResponse(url=f"/status/{active_request.id}", status_code=303)
            else:
                return RedirectResponse(url=f"/portal/{patient.uuid}", status_code=303)

    return templates.TemplateResponse("index.html", {"request": request})


# -------------------------
# Authentication
# -------------------------
@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_submit(
        request: Request,
        email: str = Form(...),
        db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    """Simple login - skip email verification for development."""
    result = await db.execute(select(Patient).where(Patient.email == email))
    patient = result.scalars().first()

    if not patient:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "No account found with this email. Please sign up first."
            }
        )

    response = RedirectResponse(url=f"/portal/{patient.uuid}", status_code=303)
    response.set_cookie(key="patient_uuid", value=str(patient.uuid), httponly=True, max_age=86400 * 30)

    return response


@router.get("/auth/verify")
async def verify_login(
        request: Request,
        token: str,
        db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    """Verify magic link and log user in."""
    email = verify_magic_link(token)

    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired login link")

    result = await db.execute(select(Patient).where(Patient.email == email))
    patient = result.scalars().first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    response = RedirectResponse(url=f"/portal/{patient.uuid}", status_code=303)
    response.set_cookie(key="patient_uuid", value=str(patient.uuid), httponly=True, max_age=86400 * 30)

    return response


# -------------------------
# Registration
# -------------------------
@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
async def register_submit(
        request: Request,
        db: AsyncSession = Depends(get_db),
        first_name: str = Form(""),
        last_name: str = Form(""),
        email: str = Form(""),
        phone: str = Form(""),
        dob: str = Form(""),
) -> RedirectResponse:
    """Create a Patient and redirect to consent."""
    if email:
        result = await db.execute(select(Patient).where(Patient.email == email))
        existing = result.scalars().first()
        if existing:
            return templates.TemplateResponse(
                "register.html",
                {
                    "request": request,
                    "error": "An account with this email already exists. Please login instead."
                }
            )

    date_of_birth = None
    if dob:
        try:
            date_of_birth = datetime.strptime(dob, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")

    patient = Patient(
        first_name=first_name or "",
        last_name=last_name or "",
        email=email or None,
        phone=phone or None,
        date_of_birth=date_of_birth
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    response = RedirectResponse(url=f"/consent/{patient.id}", status_code=303)
    response.set_cookie(key="patient_uuid", value=str(patient.uuid), httponly=True, max_age=86400 * 30)

    return response


# -------------------------
# Consent - ENHANCED v2.0
# -------------------------
@router.get("/consent/{patient_id}", response_class=HTMLResponse)
async def consent_form(
        patient_id: int,
        request: Request,
        db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    """Display the full HIPAA authorization form for patient signature."""
    res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return templates.TemplateResponse(
        "consent.html",
        {
            "request": request,
            "patient": patient
        }
    )


@router.post("/consent/{patient_id}")
async def consent_submit(
        patient_id: int,
        request: Request,
        signature_data_url: str = Form(...),
        # NEW: Initials for sensitive categories
        initial_hiv_value: str = Form(""),
        initial_genetic_value: str = Form(""),
        initial_sud_value: str = Form(""),
        initial_mental_value: str = Form(""),
        initial_psychotherapy_value: str = Form(""),
        db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    Process consent signature, generate professional PDF, and save consent record.

    ENHANCED v2.0: Now captures initials for sensitive categories and generates
    professional HIPAA-compliant authorization documents.
    """
    p = await db.get(Patient, patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Create directories for storage
    sig_dir = "storage/signatures"
    os.makedirs(sig_dir, exist_ok=True)

    # Save signature image
    try:
        b64 = signature_data_url.split(",")[-1]
        sig_bytes = base64.b64decode(b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature data: {e}")

    sig_path = os.path.join(sig_dir, f"sig_{p.id}.png")
    with open(sig_path, "wb") as f:
        f.write(sig_bytes)

    # Generate professional release PDF with new template
    release_dir = "storage/releases"
    os.makedirs(release_dir, exist_ok=True)
    release_path = os.path.join(release_dir, f"release_patient_{p.id}.pdf")

    patient_name = f"{p.first_name} {p.last_name}"
    dob_str = p.date_of_birth.isoformat() if p.date_of_birth else ""

    # ENHANCED: Use new professional PDF generation with all parameters
    generate_release_pdf(
        output_path=release_path,
        patient_name=patient_name,
        dob=dob_str,
        email=p.email or "",
        phone=p.phone or "",
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
        patient_id=p.id,
        release_text_version="v2.0",  # UPDATED: New version tracking
        consent_pdf_path=release_path,
        signature_image_path=sig_path,
        signed_at=datetime.utcnow(),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")
    )
    db.add(consent_obj)
    await db.commit()

    log.info(f"✅ Consent signed and professional PDF generated for patient {p.id}")

    return RedirectResponse(url=f"/search-providers/{p.id}", status_code=303)


# -------------------------
# Search Providers
# -------------------------
@router.get("/search-providers/{patient_id}", response_class=HTMLResponse)
async def search_providers_page(
        patient_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    """Enhanced provider search page (v2.0)."""
    res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return templates.TemplateResponse(
        "search_providers.html",
        {"request": request, "patient": patient}
    )


@router.post("/search-providers/{patient_id}", response_class=HTMLResponse)
async def search_providers_submit(
        patient_id: int,
        request: Request,
        db: AsyncSession = Depends(get_db),
        search_query: str = Form(""),
        city: str = Form(""),
        state: str = Form(""),
        zip_code: str = Form(""),
) -> HTMLResponse:
    """Process hospital search with enhanced v2.0 features."""
    res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    hospitals = []

    # Search by name if provided
    if search_query:
        hospitals = await search_hospital_by_name(search_query, limit=20)

    # Search by location if provided
    elif city and state:
        hospitals = await search_hospitals(city=city, state=state, limit=20)
    elif zip_code:
        hospitals = await search_hospitals(zip_code=zip_code, limit=20)

    return templates.TemplateResponse(
        "search_results.html",
        {
            "request": request,
            "patient": patient,
            "hospitals": hospitals,
            "search_query": search_query,
            "city": city,
            "state": state,
            "zip_code": zip_code
        }
    )


# -------------------------
# Review Providers
# -------------------------
@router.get("/review-providers/{patient_id}", response_class=HTMLResponse)
async def review_providers_page(
        patient_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    """Page to review and edit selected providers before sending faxes."""
    res = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = res.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return templates.TemplateResponse(
        "review_providers.html",
        {"request": request, "patient": patient}
    )


@router.post("/review-providers/{patient_id}")
async def review_providers_submit(
        patient_id: int,
        request: Request,
        db: AsyncSession = Depends(get_db),
        selected_providers: str = Form(""),
) -> RedirectResponse:
    """
    Process selected providers and create requests.

    ENHANCED v2.0: Now generates professional fax cover sheets with all required
    information for HIPAA-compliant medical records requests.
    """
    p = await db.get(Patient, patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")

    res_c = await db.execute(select(PatientConsent).where(PatientConsent.patient_id == p.id))
    consent = res_c.scalars().first()
    if not consent:
        raise HTTPException(status_code=400, detail="Consent missing")

    try:
        providers_data = json.loads(selected_providers) if selected_providers else []
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid provider data: {e}")

    if not providers_data:
        raise HTTPException(status_code=400, detail="No providers selected")

    # Create providers in database
    providers = []
    for pdata in providers_data:
        name = pdata.get("name")
        # Try to get fax from either 'fax' or 'medical_records_fax' key
        fax = pdata.get("fax") or pdata.get("medical_records_fax")

        if not name or not fax:
            log.warning(f"Skipping provider with missing name or fax: {pdata}")
            continue

        if not validate_fax_number(fax):
            log.warning(f"Invalid fax number for {name}: {fax}")
            continue

        fax = format_fax_number(fax)

        # Create provider record
        provider = Provider(
            name=name,
            fax=fax,  # Store the medical records fax in the fax field
            npi=pdata.get("npi"),
            address_line1=pdata.get("address"),
            city=pdata.get("city"),
            state=pdata.get("state"),
            phone=pdata.get("phone"),
            source=pdata.get("source", "manual"),
            type="hospital"
        )
        db.add(provider)
        await db.flush()
        providers.append(provider)

    if not providers:
        raise HTTPException(status_code=400, detail="No valid providers to contact")

    # Create RecordRequest
    rr = RecordRequest(
        patient_id=p.id,
        requested_cities="",
        requested_zips="",
        requested_providers_json=selected_providers,
        release_pdf_path=consent.consent_pdf_path,
        status="in_progress",
    )
    db.add(rr)
    await db.commit()
    await db.refresh(rr)

    # Prepare for fax sending
    base_url = os.getenv("BASE_EXTERNAL_URL", "")
    callback = f"{base_url}/ifax/outbound-status" if base_url else None

    covers_dir = "storage/covers"
    os.makedirs(covers_dir, exist_ok=True)

    patient_name = f"{p.first_name} {p.last_name}"
    dob_str = p.date_of_birth.isoformat() if p.date_of_birth else ""

    # Send fax to each provider with professional cover sheets
    for prov in providers:
        # ENHANCED: Generate professional cover sheet with all details
        cover_path = os.path.join(covers_dir, f"cover_rr{rr.id}_prov{prov.id}.pdf")

        # Calculate total pages (cover + release form)
        # Typically: 1 page cover + 2 pages release = 3 pages total
        total_pages = 3

        write_cover_sheet(
            path=cover_path,
            patient_name=patient_name,
            dob=dob_str,
            request_id=rr.id,
            patient_phone=p.phone or "",
            patient_email=p.email or "",
            provider_name=prov.name,
            provider_fax=prov.fax or "",
            provider_phone=prov.phone or "",
            total_pages=total_pages,
        )

        try:
            # Send fax with both cover sheet and release form
            res = send_fax(
                to_number=prov.fax,
                file_paths=[cover_path, consent.consent_pdf_path],
                cover_text=f"Medical Records Request for {patient_name}",
                callback_url=callback
            )

            if res.get("success"):
                job_id = res.get("jobId", "")
                log.info(
                    f"✅ Fax sent successfully to {prov.name} "
                    f"(Fax: {prov.fax}, Job ID: {job_id})"
                )

                pr = ProviderRequest(
                    record_request_id=rr.id,
                    provider_id=prov.id,
                    fax_number_used=prov.fax,
                    status="fax_sent",
                    outbound_job_id=job_id,
                    sent_at=datetime.utcnow()
                )
            else:
                error_msg = res.get("message", res.get("error", "Unknown error"))
                log.error(
                    f"❌ Failed to send fax to {prov.name} "
                    f"(Fax: {prov.fax}): {error_msg}"
                )

                pr = ProviderRequest(
                    record_request_id=rr.id,
                    provider_id=prov.id,
                    fax_number_used=prov.fax,
                    status="fax_failed",
                    failed_reason=error_msg
                )

        except Exception as e:
            log.exception(
                f"❌ Exception sending fax to {prov.name} "
                f"(Fax: {prov.fax}): {e}"
            )

            pr = ProviderRequest(
                record_request_id=rr.id,
                provider_id=prov.id,
                fax_number_used=prov.fax,
                status="fax_failed",
                failed_reason=str(e)
            )

        db.add(pr)

    await db.commit()

    log.info(
        f"✅ Record request {rr.id} created with {len(providers)} providers. "
        f"Faxes sent with professional cover sheets and release forms."
    )

    return RedirectResponse(url=f"/status/{rr.id}", status_code=303)


# -------------------------
# Status page
# -------------------------
@router.get("/status/{request_id}", response_class=HTMLResponse)
async def status_page(
        request_id: int,
        request: Request,
        db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Render the status page with all relationships preloaded via JOINs."""
    q = (
        select(RecordRequest)
        .options(
            joinedload(RecordRequest.patient),
            joinedload(RecordRequest.provider_requests).joinedload(ProviderRequest.provider),
        )
        .where(RecordRequest.id == request_id)
    )
    result = await db.execute(q)
    rr = result.unique().scalar_one_or_none()
    if rr is None:
        raise HTTPException(status_code=404, detail="Record request not found")

    prs: List[ProviderRequest] = list(rr.provider_requests or [])

    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "rr": rr,
            "prs": prs,
            "patient": rr.patient,
            "portal_url": f"/portal/{rr.patient.uuid}",
            "add_providers_url": f"/search-providers/{rr.patient_id}",
            "cancel_url": f"/cancel-request/{rr.id}"
        }
    )


# -------------------------
# Cancel Request
# -------------------------
@router.post("/cancel-request/{request_id}")
async def cancel_request(
        request_id: int,
        request: Request,
        db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Cancel a record request and allow user to start over."""
    rr = await db.get(RecordRequest, request_id)
    if not rr:
        raise HTTPException(status_code=404, detail="Record request not found")

    rr.status = "cancelled"
    await db.commit()

    return RedirectResponse(url=f"/search-providers/{rr.patient_id}", status_code=303)