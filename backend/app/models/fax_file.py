"""
Updated FaxFile Model - v2.0

Changes:
- Added encounter_date field to store date of clinical encounter
- This enables chronological ordering of medical records by service date
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, LargeBinary, Text, Date
from sqlalchemy.orm import relationship
from app.database.db import Base


class FaxFile(Base):
    """
    Represents an incoming fax containing medical records.

    Attributes:
        id: Primary key
        patient_id: Foreign key to Patient
        job_id: iFax job identifier
        transaction_id: iFax transaction identifier
        sender: Fax number of sender (healthcare provider)
        receiver: Fax number of receiver (our service)
        received_time: When fax was received
        file_path: Path to PDF file on disk
        pdf_data: Binary PDF data
        ocr_text: Extracted text from OCR processing
        encounter_date: Date when medical services were provided (NEW)

    The encounter_date field stores the "Date of Service", "Visit Date", etc.
    extracted from the medical record. This is used for chronological ordering
    when compiling multiple records for a patient.
    """
    __tablename__ = "fax_files"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    job_id = Column(String, nullable=True)
    transaction_id = Column(String, nullable=True)
    sender = Column(String, nullable=True)
    receiver = Column(String, nullable=True)
    received_time = Column(DateTime, default=datetime.utcnow)
    file_path = Column(String, nullable=True)
    pdf_data = Column(LargeBinary, nullable=True)
    ocr_text = Column(Text, nullable=True)

    # NEW: Date of clinical encounter (when services were provided)
    # Parsed from "Date of Service", "Visit Date", "Encounter Date", etc.
    # Used for chronological ordering when compiling records
    encounter_date = Column(Date, nullable=True)

    patient = relationship("Patient", backref="faxes")

    def __repr__(self):
        return (
            f"<FaxFile(id={self.id}, patient_id={self.patient_id}, "
            f"job_id={self.job_id}, encounter_date={self.encounter_date})>"
        )