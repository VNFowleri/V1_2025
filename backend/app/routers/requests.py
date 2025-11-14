import os, json
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database.db import get_db
from app.models import Patient, Provider, PatientConsent, RecordRequest, ProviderRequest
from app.services.ifax_service import send_fax
from app.services.pdf_ops import write_cover_sheet

router = APIRouter()

class ProviderInput(BaseModel):
    name: str
    fax: str
    npi: str = None

class RequestCreate(BaseModel):
    patient_id: int
    provider_ids: List[int] = []
    manual_providers: List[ProviderInput] = []

@router.post("/")
async def create_request(req: RequestCreate, db: AsyncSession = Depends(get_db)):
    patient = await db.get(Patient, req.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    res = await db.execute(select(PatientConsent).where(PatientConsent.patient_id == patient.id))
    consent = res.scalars().first()
    if not consent:
        raise HTTPException(status_code=400, detail="Consent missing")

    rr = RecordRequest(patient_id=patient.id, status="in_progress", release_pdf_path=consent.consent_pdf_path)
    db.add(rr); await db.commit(); await db.refresh(rr)

    providers = []
    for pid in req.provider_ids:
        p = await db.get(Provider, pid)
        if p: providers.append(p)
    for mp in req.manual_providers:
        p = Provider(name=mp.name, fax=mp.fax, npi=mp.npi, source="manual")
        db.add(p); await db.flush()
        providers.append(p)
    await db.commit()

    base_url = os.getenv("BASE_EXTERNAL_URL", "")
    callback = f"{base_url}/ifax/outbound-status" if base_url else None

    for prov in providers:
        if not prov.fax:
            pr = ProviderRequest(record_request_id=rr.id, provider_id=prov.id, status="queued")
            db.add(pr); continue

        cover_dir = "storage/covers"; os.makedirs(cover_dir, exist_ok=True)
        cover_path = os.path.join(cover_dir, f"cover_rr{rr.id}_prov{prov.id}.pdf")
        patient_name = f"{patient.first_name} {patient.last_name}"
        dob_str = patient.date_of_birth.isoformat() if patient.date_of_birth else ""
        write_cover_sheet(cover_path, patient_name=patient_name, dob=dob_str, request_id=rr.id)
        res = send_fax(to_number=prov.fax, file_paths=[cover_path, consent.consent_pdf_path], cover_text=None, callback_url=callback)
        job_id = str(res.get("jobId") or res.get("data", {}).get("jobId") or "")
        pr = ProviderRequest(record_request_id=rr.id, provider_id=prov.id, fax_number_used=prov.fax, status="fax_sent", outbound_job_id=job_id, sent_at=datetime.utcnow())
        db.add(pr)

    await db.commit()
    return {"request_id": rr.id}
