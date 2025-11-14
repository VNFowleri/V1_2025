import json, os
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from starlette.templating import Jinja2Templates
from starlette.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.db import get_db
from app.models import Patient, Provider, RecordRequest, PatientConsent, ProviderRequest
from app.services.provider_directory import search_providers
from app.services.ifax_service import send_fax
from app.services.pdf_ops import write_cover_sheet

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/{patient_id}")
async def providers_form(request: Request, patient_id: int, db: AsyncSession = Depends(get_db)):
    p = await db.get(Patient, patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return templates.TemplateResponse("providers.html", {"request": request, "patient": p})

@router.post("/{patient_id}")
async def providers_submit(request: Request,
                           patient_id: int,
                           cities: str = Form(""),
                           zips: str = Form(""),
                           manual_providers_json: str = Form(""),
                           db: AsyncSession = Depends(get_db)):
    p = await db.get(Patient, patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")

    res_c = await db.execute(select(PatientConsent).where(PatientConsent.patient_id == p.id))
    consent = res_c.scalars().first()
    if not consent:
        raise HTTPException(status_code=400, detail="Consent missing")

    found = []
    for city in [c.strip() for c in cities.split(",") if c.strip()]:
        results = search_providers(city=city, limit=15)
        found.extend(results)
    for z in [z.strip() for z in zips.split(",") if z.strip()]:
        results = search_providers(postal_code=z, limit=15)
        found.extend(results)

    providers = []
    for pr in found:
        existing = await db.execute(select(Provider).where(Provider.npi == pr.get("npi")))
        ex = existing.scalars().first()
        if not ex:
            ex = Provider(**pr); db.add(ex); await db.flush()
        providers.append(ex)

    try:
        manual = json.loads(manual_providers_json) if manual_providers_json.strip() else []
    except Exception:
        manual = []
    for mp in manual:
        name = mp.get("name"); fax = mp.get("fax")
        if not name: continue
        ex = Provider(name=name, fax=fax, source="manual")
        db.add(ex); await db.flush()
        providers.append(ex)

    rr = RecordRequest(
        patient_id=p.id,
        requested_cities=cities,
        requested_zips=zips,
        requested_providers_json=manual_providers_json or "{}",
        release_pdf_path=consent.consent_pdf_path,
        status="in_progress",
    )
    db.add(rr); await db.commit(); await db.refresh(rr)

    base_url = os.getenv("BASE_EXTERNAL_URL", "")
    callback = f"{base_url}/ifax/outbound-status" if base_url else None

    covers_dir = "storage/covers"; os.makedirs(covers_dir, exist_ok=True)
    patient_name = f"{p.first_name} {p.last_name}"
    dob_str = p.date_of_birth.isoformat() if p.date_of_birth else ""

    for prov in providers:
        if not prov.fax:
            pr = ProviderRequest(record_request_id=rr.id, provider_id=prov.id, status="queued")
            db.add(pr); continue

        cover_path = os.path.join(covers_dir, f"cover_rr{rr.id}_prov{prov.id}.pdf")
        write_cover_sheet(cover_path, patient_name=patient_name, dob=dob_str, request_id=rr.id)
        res = send_fax(to_number=prov.fax, file_paths=[cover_path, consent.consent_pdf_path], cover_text=None, callback_url=callback)
        job_id = str(res.get("jobId") or res.get("data", {}).get("jobId") or "")
        pr = ProviderRequest(record_request_id=rr.id, provider_id=prov.id, fax_number_used=prov.fax, status="fax_sent", outbound_job_id=job_id, sent_at=datetime.utcnow())
        db.add(pr)

    await db.commit()

    return RedirectResponse(url=f"/status/{rr.id}", status_code=303)