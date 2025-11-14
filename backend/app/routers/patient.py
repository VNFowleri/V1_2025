from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import get_db
from app.models import Patient

router = APIRouter()

class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None

class PatientOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str]
    phone: Optional[str]
    date_of_birth: Optional[date]
    class Config:
        orm_mode = True

@router.post("/", response_model=PatientOut)
async def create_patient(patient_in: PatientCreate, db: AsyncSession = Depends(get_db)):
    dob = None
    if patient_in.date_of_birth:
        dob = datetime.strptime(patient_in.date_of_birth, "%Y-%m-%d").date()
    p = Patient(first_name=patient_in.first_name, last_name=patient_in.last_name, email=patient_in.email, phone=patient_in.phone, date_of_birth=dob)
    db.add(p); await db.commit(); await db.refresh(p)
    return p

@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(patient_id: int, db: AsyncSession = Depends(get_db)):
    p = await db.get(Patient, patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return p
