"""
HumbleFax Integration Router

Handles incoming and outbound fax webhooks from HumbleFax service.
Integrated with OCR processing and patient matching.
"""

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db, get_async_session_context
from app.models.fax_file import FaxFile
from app.models.record_request import ProviderRequest, RecordRequest
from app.services.humblefax_service import download_incoming_fax
from app.services.ocr_service import extract_text_from_pdf
from app.services.fax_processor import IncomingFaxProcessor

logger = logging.getLogger(__name__)

# ============================================================================
# ROUTER SETUP
# ============================================================================

router = APIRouter(prefix="/humblefax", tags=["HumbleFax"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class IncomingFaxData(BaseModel):
    """Inner fax data structure from HumbleFax webhook"""
    id: int
    status: str
    time: Optional[str] = None
    toNumber: Optional[str] = None
    fromNameAddressBook: Optional[str] = None
    fromNameIdentity: Optional[str] = None
    fromNumber: Optional[str] = None
    numPages: Optional[str] = None
    transmissionTime: Optional[str] = None
    bitRate: Optional[str] = None

    class Config:
        extra = "allow"


class HumbleFaxInboundPayload(BaseModel):
    """Webhook payload structure for incoming faxes from HumbleFax."""
    type: str
    data: dict
    time: int
    numAttempts: Optional[int] = None
    webhookId: Optional[int] = None
    webhookMsgId: Optional[str] = None

    class Config:
        extra = "allow"

    def get_fax_data(self) -> IncomingFaxData:
        """Extract fax data from nested structure"""
        fax_dict = self.data.get("IncomingFax") or self.data.get("incomingFax")
        if not fax_dict:
            raise ValueError("No IncomingFax data found in payload")
        return IncomingFaxData(**fax_dict)


class HumbleFaxOutboundPayload(BaseModel):
    """Webhook payload for outbound fax status updates."""
    id: str
    status: str
    completedAt: Optional[str] = None
    error: Optional[str] = None

    class Config:
        extra = "allow"


# ============================================================================
# BACKGROUND PROCESSING - COMPLETE PIPELINE
# ============================================================================

async def process_incoming_fax_background(
        fax_id: str,
        fax_record_id: int
):
    """
    Background task for processing incoming fax from HumbleFax.

    Complete pipeline:
    1. Download PDF from HumbleFax
    2. Save to filesystem
    3. Run OCR (with proper error handling)
    4. Parse encounter date
    5. Match patient (name + DOB)
    6. Match provider request
    7. Check if request is complete
    """
    logger.info(f"🔄 Background processing started: FaxFile #{fax_record_id}")

    try:
        async with get_async_session_context() as db:
            # Get the fax record
            result = await db.execute(
                select(FaxFile).where(FaxFile.id == fax_record_id)
            )
            fax = result.scalar_one_or_none()

            if not fax:
                logger.error(f"❌ FaxFile {fax_record_id} not found in database")
                return

            # ================================================================
            # STEP 1: Download PDF from HumbleFax
            # ================================================================
            if not fax.pdf_data or len(fax.pdf_data) == 0:
                logger.info("📥 Downloading PDF from HumbleFax...")

                download_result = download_incoming_fax(fax_id, save_to_disk=True)

                if download_result["success"]:
                    fax.pdf_data = download_result["pdf_bytes"]
                    if "file_path" in download_result:
                        fax.file_path = download_result["file_path"]
                    await db.commit()

                    logger.info(
                        f"✅ Downloaded PDF: {len(fax.pdf_data)} bytes, "
                        f"saved to {fax.file_path}"
                    )
                else:
                    logger.error(
                        f"❌ Failed to download PDF: "
                        f"{download_result.get('message', 'Unknown error')}"
                    )
                    fax.ocr_text = f"[ERROR: Failed to download PDF - {download_result.get('message')}]"
                    await db.commit()
                    return

            # Ensure file is saved to filesystem
            if fax.pdf_data and not fax.file_path:
                logger.info("💾 Saving PDF to filesystem...")
                try:
                    out_dir = "received_faxes"
                    os.makedirs(out_dir, exist_ok=True)
                    file_path = os.path.join(out_dir, f"{fax_id}.pdf")

                    with open(file_path, "wb") as f:
                        f.write(fax.pdf_data)

                    fax.file_path = file_path
                    await db.commit()
                    logger.info(f"✅ Saved PDF to filesystem: {file_path}")
                except Exception as e:
                    logger.error(f"❌ Error saving PDF: {e}")

            # ================================================================
            # STEP 2: Run OCR with proper error handling
            # ================================================================
            if not fax.ocr_text or fax.ocr_text.startswith("[ERROR:"):
                logger.info("📄 Running OCR on PDF...")
                try:
                    ocr_text = extract_text_from_pdf(fax.file_path)

                    if not ocr_text or len(ocr_text.strip()) == 0:
                        logger.error("❌ OCR returned empty text")
                        logger.error(f"PDF file exists: {os.path.exists(fax.file_path)}")
                        logger.error(f"PDF file size: {os.path.getsize(fax.file_path)} bytes")
                        fax.ocr_text = "[OCR FAILED - Empty result]"
                        await db.commit()
                        return

                    fax.ocr_text = ocr_text
                    await db.commit()
                    logger.info(f"✅ OCR complete: {len(ocr_text)} characters extracted")
                    logger.debug(f"OCR text preview: {ocr_text[:200]}...")

                except Exception as e:
                    logger.error(f"❌ OCR failed: {e}", exc_info=True)
                    fax.ocr_text = f"[OCR ERROR: {str(e)}]"
                    await db.commit()
                    return

            # ================================================================
            # STEP 3-6: Process with IncomingFaxProcessor
            # This handles:
            # - Parsing encounter date
            # - Matching to patient
            # - Matching to provider requests
            # ================================================================
            logger.info("🔍 Processing fax content (patient matching, date parsing, provider matching)...")
            try:
                processor = IncomingFaxProcessor(db)
                success = await processor.process_incoming_fax(
                    job_id=fax_id,
                    fax_file=fax
                )

                if success:
                    logger.info("✅ Fax processing complete - patient matched and linked")
                else:
                    logger.warning("⚠️ Fax processing completed but patient matching may have failed")

            except Exception as e:
                logger.error(f"❌ Error in fax processor: {str(e)}", exc_info=True)
                # Don't return - continue to mark as complete

            logger.info(f"✅ Background processing complete: FaxFile #{fax_record_id}")

    except Exception as e:
        logger.exception(f"❌ Fatal error in background processing: {e}")


# ============================================================================
# WEBHOOK ENDPOINT - INCOMING FAXES
# ============================================================================

@router.post("/receive")
async def receive_fax_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        db: AsyncSession = Depends(get_db)
):
    """
    Webhook endpoint for receiving incoming faxes from HumbleFax.

    Configure this URL in your HumbleFax dashboard:
    https://app.humblefax.com/?category=developer-settings

    Webhook URL: https://your-domain.com/humblefax/receive
    """
    logger.info("=" * 80)
    logger.info("📨 HumbleFax incoming fax webhook received")

    # Parse and validate payload
    try:
        payload_data = await request.json()
        logger.info(f"Payload data: {payload_data}")

        payload = HumbleFaxInboundPayload(**payload_data)
        fax_data = payload.get_fax_data()

        logger.info(
            f"✅ Valid payload: "
            f"Type={payload.type}, "
            f"FaxID={fax_data.id}, "
            f"From={fax_data.fromNumber}, "
            f"To={fax_data.toNumber}, "
            f"Pages={fax_data.numPages}, "
            f"Status={fax_data.status}"
        )

    except ValueError as e:
        logger.error(f"❌ Invalid payload structure: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid webhook payload: {str(e)}"
        )
    except Exception as e:
        logger.error(f"❌ Error parsing payload: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse payload: {str(e)}"
        )

    # Extract fax data
    fax_id = str(fax_data.id)

    # Check for duplicate faxes (idempotency)
    try:
        result = await db.execute(
            select(FaxFile).where(FaxFile.job_id == fax_id)
        )
        existing_fax = result.scalar_one_or_none()

        if existing_fax:
            logger.warning(
                f"⚠️ Duplicate fax webhook: {fax_id} "
                f"(already processed as FaxFile #{existing_fax.id})"
            )
            return {
                "status": "duplicate",
                "message": "Fax already processed",
                "fax_id": existing_fax.id,
                "humblefax_id": fax_id
            }
    except Exception as e:
        logger.error(f"❌ Error checking for duplicates: {e}")

    # Parse received time
    received_time = datetime.utcnow()
    if fax_data.time:
        try:
            received_time = datetime.fromtimestamp(int(fax_data.time))
            logger.debug(f"Parsed received time: {received_time}")
        except Exception as e:
            logger.warning(f"Could not parse time: {e}")

    # Create FaxFile record immediately
    try:
        fax = FaxFile(
            job_id=fax_id,
            transaction_id=fax_id,
            sender=fax_data.fromNumber or "",
            receiver=fax_data.toNumber or "",
            received_time=received_time,
            file_path="",
            pdf_data=b"",
            ocr_text=""
        )
        db.add(fax)
        await db.commit()
        await db.refresh(fax)

        logger.info(
            f"✅ Created FaxFile record: "
            f"ID={fax.id}, HumbleFaxID={fax_id}"
        )
    except Exception as e:
        await db.rollback()
        logger.exception(f"❌ Failed to create FaxFile record: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )

    # Queue background processing
    background_tasks.add_task(
        process_incoming_fax_background,
        fax_id=fax_id,
        fax_record_id=fax.id
    )

    logger.info(
        f"✅ Queued background processing: "
        f"FaxFile #{fax.id}, HumbleFaxID={fax_id}"
    )
    logger.info("=" * 80)

    return {
        "status": "accepted",
        "message": "Fax received and queued for processing",
        "fax_id": fax.id,
        "humblefax_id": fax_id
    }


# ============================================================================
# WEBHOOK ENDPOINT - OUTBOUND STATUS UPDATES
# ============================================================================

@router.post("/outbound-status")
async def outbound_status_webhook(
        request: Request,
        db: AsyncSession = Depends(get_db)
):
    """
    Webhook endpoint for outbound fax status updates from HumbleFax.

    Updates ProviderRequest status based on fax delivery status.
    """
    logger.info("=" * 80)
    logger.info("📤 HumbleFax outbound status webhook received")

    try:
        payload_data = await request.json()
        logger.info(f"Payload data: {payload_data}")

        payload = HumbleFaxOutboundPayload(**payload_data)
        logger.info(f"✅ Valid payload: FaxID={payload.id}, Status={payload.status}")

    except ValueError as e:
        logger.error(f"❌ Invalid payload structure: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid webhook payload: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error parsing payload: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to parse payload: {str(e)}")

    # Find the provider request by outbound_job_id
    try:
        result = await db.execute(
            select(ProviderRequest).where(ProviderRequest.outbound_job_id == payload.id)
        )
        provider_request = result.scalar_one_or_none()

        if not provider_request:
            logger.warning(f"⚠️ No provider request found for fax ID: {payload.id}")
            return {
                "status": "not_found",
                "message": "Provider request not found",
                "fax_id": payload.id
            }

        # Update status based on HumbleFax status
        if payload.status == "delivered":
            provider_request.status = "fax_delivered"
            provider_request.delivered_at = datetime.utcnow()
            logger.info(f"✅ Marked provider request #{provider_request.id} as delivered")

        elif payload.status == "failed":
            provider_request.status = "fax_failed"
            provider_request.failed_reason = payload.error or "Unknown error"
            logger.info(
                f"❌ Marked provider request #{provider_request.id} as failed: "
                f"{provider_request.failed_reason}"
            )

        elif payload.status == "sent":
            provider_request.status = "fax_sent"
            logger.info(f"ℹ️ Provider request #{provider_request.id} marked as sent")

        await db.commit()
        logger.info("=" * 80)

        return {
            "status": "updated",
            "message": "Provider request status updated",
            "provider_request_id": provider_request.id,
            "new_status": provider_request.status
        }

    except Exception as e:
        await db.rollback()
        logger.exception(f"❌ Error updating provider request: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.get("/health")
async def health_check():
    """Health check endpoint for monitoring HumbleFax integration."""
    return {
        "status": "healthy",
        "service": "HumbleFax Integration",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": {
            "incoming": "/humblefax/receive",
            "outbound": "/humblefax/outbound-status",
            "status": "/humblefax/status/{fax_id}"
        }
    }


@router.get("/status/{fax_id}")
async def get_fax_status(fax_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get the processing status of a specific fax.

    Useful for debugging and monitoring.
    """
    # Try to find by job_id first
    result = await db.execute(select(FaxFile).where(FaxFile.job_id == fax_id))
    fax = result.scalar_one_or_none()

    # If not found, try by database ID
    if not fax:
        try:
            fax_id_int = int(fax_id)
            result = await db.execute(select(FaxFile).where(FaxFile.id == fax_id_int))
            fax = result.scalar_one_or_none()
        except ValueError:
            pass

    if not fax:
        raise HTTPException(status_code=404, detail=f"Fax not found: {fax_id}")

    return {
        "fax_id": fax.id,
        "job_id": fax.job_id,
        "sender": fax.sender,
        "receiver": fax.receiver,
        "received_time": fax.received_time.isoformat() if fax.received_time else None,
        "patient_id": fax.patient_id,
        "file_path": fax.file_path,
        "has_pdf": len(fax.pdf_data) > 0 if fax.pdf_data else False,
        "has_ocr": bool(fax.ocr_text),
        "ocr_length": len(fax.ocr_text) if fax.ocr_text else 0,
        "ocr_snippet": fax.ocr_text[:200] if fax.ocr_text else None,
        "encounter_date": fax.encounter_date.isoformat() if fax.encounter_date else None
    }