from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.db import Base

class RecordRequest(Base):
    __tablename__ = "record_requests"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending|in_progress|waiting|complete
    requested_cities = Column(Text, nullable=True)  # comma-separated
    requested_zips = Column(Text, nullable=True)    # comma-separated
    requested_providers_json = Column(Text, nullable=True)  # JSON of manual providers
    release_pdf_path = Column(String, nullable=False)
    compiled_pdf_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    patient = relationship("Patient", backref="record_requests")


class ProviderRequest(Base):
    __tablename__ = "provider_requests"

    id = Column(Integer, primary_key=True)
    record_request_id = Column(Integer, ForeignKey("record_requests.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=True)
    fax_number_used = Column(String, nullable=True)

    status = Column(String, nullable=False, default="queued")  # queued|fax_sent|fax_delivered|fax_failed|response_received
    outbound_job_id = Column(String, nullable=True)
    outbound_transaction_id = Column(String, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    failed_reason = Column(Text, nullable=True)

    inbound_fax_id = Column(Integer, ForeignKey("fax_files.id"), nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    record_request = relationship("RecordRequest", backref="provider_requests")
    provider = relationship("Provider", backref="requests")