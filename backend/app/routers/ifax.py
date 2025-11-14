# app/routers/ifax.py - v2.0
"""
Enhanced iFax Webhook Router

Handles incoming webhooks from iFax API for:
1. Inbound faxes (incoming medical records)
2. Outbound fax status updates (delivery confirmations)

Key improvements:
- Comprehensive error handling and logging
- Background processing with status tracking
- Detailed webhook payload validation
- Support for retry mechanisms
- Enhanced status reporting
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
import logging
from pydantic import BaseModel, Field
from typing import Optional

from app.database.db import get_db, AsyncSessionLocal
from app.models import FaxFile, ProviderRequest
from app.services.fax_processor import process_incoming_fax

router = APIRouter()
logger = logging.getLogger(__name__)


class FaxWebhookPayload(BaseModel):
    """
    iFax webhook payload structure for incoming faxes.

    Example payload:
    {
        "jobId": 12345,
        "transactionId": 67890,
        "fromNumber": "+15551234567",
        "toNumber": "+15559876543",
        "faxCallStart": 1699564800,
        "faxReceivedPages": 5,
        "faxStatus": "received",
        "message": "Fax received successfully",
        "code": 200,
        "direction": "inbound"
    }
    """
    jobId: int
    transactionId: int
    fromNumber: Optional[str] = None
    toNumber: Optional[str] = None
    faxCallStart: int
    faxReceivedPages: int = Field(..., alias="faxReceivedPages")
    faxStatus: str
    message: Optional[str] = None
    code: Optional[int] = None
    direction: Optional[str] = None

    class Config:
        extra = "allow"  # Allow additional fields from iFax


@router.post("/receive")
async def receive_fax_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        db: AsyncSession = Depends(get_db)
):
    """
    Webhook endpoint for receiving incoming faxes from iFax.

    This endpoint:
    1. Validates the webhook payload
    2. Creates a FaxFile database record immediately
    3. Queues background processing for:
       - Downloading the fax PDF
       - OCR text extraction
       - Patient matching
       - Provider request matching
       - Aggregation when complete

    Returns immediately with 200 OK to iFax, processing continues in background.
    """
    # Log raw request for debugging
    logger.info("=" * 80)
    logger.info("📨 Incoming fax webhook received")
    logger.info(f"Headers: {dict(request.headers)}")

    try:
        payload_data = await request.json()
        logger.info(f"Raw payload: {payload_data}")

        # Validate payload structure
        payload = FaxWebhookPayload(**payload_data)
        logger.info(
            f"✅ Valid payload: JobID={payload.jobId}, "
            f"TransactionID={payload.transactionId}, "
            f"From={payload.fromNumber}, "
            f"Pages={payload.faxReceivedPages}"
        )

    except ValueError as e:
        logger.error(f"❌ Invalid payload structure: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error parsing payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Create FaxFile record immediately
    try:
        fax = FaxFile(
            job_id=str(payload.jobId),
            transaction_id=str(payload.transactionId),
            sender=payload.fromNumber or "",
            receiver=payload.toNumber or "",
            received_time=datetime.utcfromtimestamp(payload.faxCallStart),
            file_path="",  # Will be populated during processing
            pdf_data=b"",  # Will be populated during processing
            ocr_text="",  # Will be populated during processing
        )

        db.add(fax)
        await db.commit()
        await db.refresh(fax)

        logger.info(
            f"✅ Created FaxFile record: ID={fax.id}, JobID={payload.jobId}"
        )

    except Exception as e:
        logger.exception(f"❌ Failed to create FaxFile record: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )

    # Queue background processing
    background_tasks.add_task(
        process_fax_background,
        job_id=str(payload.jobId),
        fax_record_id=fax.id,
        transaction_id=payload.transactionId,
        direction=payload.direction
    )

    logger.info(
        f"✅ Queued background processing for FaxID={fax.id}, JobID={payload.jobId}"
    )
    logger.info("=" * 80)

    # Return success immediately (don't make iFax wait)
    return {
        "status": "ok",
        "message": "Fax received and queued for processing",
        "fax_id": fax.id,
        "job_id": str(payload.jobId)
    }


async def process_fax_background(
        job_id: str,
        fax_record_id: int,
        transaction_id: int,
        direction: Optional[str] = None
):
    """
    Background task for processing incoming fax.

    This runs asynchronously after the webhook returns 200 OK to iFax.
    Handles the complete processing pipeline:
    - Download PDF
    - OCR extraction
    - Patient matching
    - Provider matching
    - Request completion and PDF compilation
    """
    logger.info(f"🚀 Starting background processing for FaxID={fax_record_id}")

    try:
        # Use a new database session for background processing
        async with AsyncSessionLocal() as db:
            result = await process_incoming_fax(
                job_id=job_id,
                fax_record_id=fax_record_id,
                transaction_id=transaction_id,
                db=db,
                direction=direction
            )

            logger.info(
                f"✅ Background processing complete for FaxID={fax_record_id}: "
                f"{result}"
            )

            if not result["success"]:
                logger.error(
                    f"⚠️ Processing had errors: {result.get('errors', [])}"
                )

            # Log summary
            if result["patient_matched"]:
                logger.info(
                    f"  📋 Patient matched: ID={result['patient_id']}"
                )

            if result["provider_matched"]:
                logger.info(
                    f"  🏥 Provider matched: {len(result['provider_request_ids'])} request(s)"
                )

            if result["request_completed"]:
                logger.info(
                    f"  📦 Request(s) completed: {result['completed_request_ids']}"
                )

    except Exception as e:
        logger.exception(
            f"❌ Fatal error in background processing for FaxID={fax_record_id}: {e}"
        )


@router.post("/outbound-status")
async def outbound_status_webhook(
        request: Request,
        db: AsyncSession = Depends(get_db)
):
    """
    Webhook endpoint for outbound fax status updates from iFax.

    This endpoint receives status updates for faxes we sent out:
    - fax_sent: Fax has been queued and sent
    - delivered: Fax successfully delivered to recipient
    - failed: Fax delivery failed

    Updates the corresponding ProviderRequest status in our database.
    """
    logger.info("📤 Outbound fax status webhook received")

    try:
        payload = await request.json()
        logger.info(f"Status payload: {payload}")

        job_id = str(payload.get("jobId", ""))
        status = (payload.get("faxStatus") or payload.get("status") or "").lower()
        message = payload.get("message", "")

        if not job_id:
            logger.warning("⚠️ No jobId in outbound status payload")
            return {"status": "ok", "message": "No jobId provided"}

        # Find the ProviderRequest with this job_id
        result = await db.execute(
            select(ProviderRequest).where(
                ProviderRequest.outbound_job_id == job_id
            )
        )
        provider_request = result.scalars().first()

        if not provider_request:
            logger.warning(
                f"⚠️ No ProviderRequest found for JobID={job_id}"
            )
            return {"status": "ok", "message": f"No request found for jobId {job_id}"}

        # Update status based on iFax status
        old_status = provider_request.status

        if status in ("success", "delivered", "ok"):
            provider_request.status = "fax_delivered"
            provider_request.delivered_at = datetime.utcnow()
            logger.info(
                f"✅ Fax delivered: ProviderRequest={provider_request.id}, "
                f"JobID={job_id}"
            )

        elif status in ("failed", "error"):
            provider_request.status = "fax_failed"
            provider_request.failed_reason = message
            logger.warning(
                f"❌ Fax failed: ProviderRequest={provider_request.id}, "
                f"JobID={job_id}, Reason={message}"
            )
        else:
            # Unknown status, log but don't update
            logger.warning(
                f"⚠️ Unknown status '{status}' for JobID={job_id}"
            )
            return {"status": "ok", "message": f"Unknown status: {status}"}

        # Save updates
        db.add(provider_request)
        await db.commit()

        logger.info(
            f"✅ Updated ProviderRequest {provider_request.id}: "
            f"{old_status} → {provider_request.status}"
        )

        return {
            "status": "ok",
            "message": "Status updated",
            "provider_request_id": provider_request.id,
            "old_status": old_status,
            "new_status": provider_request.status
        }

    except Exception as e:
        logger.exception(f"❌ Error processing outbound status: {e}")
        # Return 200 even on error so iFax doesn't retry
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/status/{fax_id}")
async def get_fax_processing_status(
        fax_id: int,
        db: AsyncSession = Depends(get_db)
):
    """
    Get the processing status of a specific fax.

    Useful for debugging and monitoring.
    """
    fax = await db.get(FaxFile, fax_id)

    if not fax:
        raise HTTPException(status_code=404, detail="Fax not found")

    # Check if patient was matched
    patient_matched = fax.patient_id is not None

    # Check if linked to any provider requests
    if fax.patient_id:
        pr_result = await db.execute(
            select(ProviderRequest).where(
                ProviderRequest.inbound_fax_id == fax_id
            )
        )
        provider_requests = pr_result.scalars().all()
    else:
        provider_requests = []

    return {
        "fax_id": fax.id,
        "job_id": fax.job_id,
        "transaction_id": fax.transaction_id,
        "sender": fax.sender,
        "receiver": fax.receiver,
        "received_time": fax.received_time.isoformat() if fax.received_time else None,
        "has_pdf": bool(fax.pdf_data),
        "has_ocr_text": bool(fax.ocr_text),
        "ocr_text_length": len(fax.ocr_text) if fax.ocr_text else 0,
        "patient_matched": patient_matched,
        "patient_id": fax.patient_id,
        "provider_requests_matched": len(provider_requests),
        "provider_request_ids": [pr.id for pr in provider_requests],
        "file_path": fax.file_path
    }


@router.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring.
    """
    return {
        "status": "healthy",
        "service": "iFax Webhook Handler",
        "version": "2.0"
    }