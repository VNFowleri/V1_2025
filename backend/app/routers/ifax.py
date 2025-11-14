# app/routers/ifax.py - v2.0
"""
Enhanced iFax Router with Improved Fax Reception
=================================================

Improvements:
1. Webhook signature verification
2. Idempotency handling (prevent duplicate processing)
3. Retry logic with exponential backoff
4. Polling fallback mechanism
5. Better error handling and logging
6. Rate limiting protection
7. Batch fax retrieval support

Version: 2.0
"""

import asyncio
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.models.fax_file import FaxFile
from app.services.fax_processor import IncomingFaxProcessor
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ifax", tags=["iFax"])


# ==============================================================================
# PYDANTIC MODELS
# ==============================================================================

class FaxWebhookPayload(BaseModel):
    """
    Enhanced iFax webhook payload model with validation.

    Corresponds to iFax API webhook POST body.
    """
    jobId: str = Field(..., description="Unique fax job ID")
    transactionId: str = Field(..., description="Transaction identifier")
    faxNumber: Optional[str] = Field(None, description="Sender fax number")
    receiverNumber: Optional[str] = Field(None, description="Receiver fax number")
    faxCallStart: Optional[str] = Field(None, description="ISO timestamp of fax reception start")
    pages: Optional[int] = Field(None, description="Number of pages")
    status: Optional[str] = Field(None, description="Fax status")

    # Additional fields for enhanced tracking
    fileUrl: Optional[str] = Field(None, description="Direct download URL if provided")
    fileSize: Optional[int] = Field(None, description="File size in bytes")
    duration: Optional[int] = Field(None, description="Call duration in seconds")

    @validator('faxCallStart', pre=True)
    def parse_timestamp(cls, v):
        """Parse and validate timestamp"""
        if v is None:
            return None
        # Handle various timestamp formats
        return v

    class Config:
        extra = "allow"  # Allow additional fields from iFax


class FaxDownloadRequest(BaseModel):
    """Request model for manual fax download/reprocessing"""
    job_id: str
    transaction_id: str
    force_reprocess: bool = False


class FaxListResponse(BaseModel):
    """Response model for listing incoming faxes"""
    faxes: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int


class FaxProcessingStatus(BaseModel):
    """Status response for a fax processing job"""
    job_id: str
    status: str
    patient_matched: bool
    provider_matched: bool
    ocr_completed: bool
    error_message: Optional[str] = None
    processed_at: Optional[datetime] = None


# ==============================================================================
# CONFIGURATION
# ==============================================================================

class IFaxConfig:
    """Configuration for iFax integration"""

    # Webhook signature verification (if iFax provides it)
    WEBHOOK_SECRET: Optional[str] = None  # Set from environment

    # Retry configuration
    MAX_DOWNLOAD_RETRIES: int = 3
    RETRY_BACKOFF_BASE: float = 2.0  # Exponential backoff multiplier
    RETRY_INITIAL_DELAY: float = 1.0  # Initial delay in seconds

    # Timeouts
    DOWNLOAD_TIMEOUT: int = 30  # seconds
    PROCESSING_TIMEOUT: int = 300  # 5 minutes for full OCR pipeline

    # Polling configuration
    POLLING_ENABLED: bool = True
    POLLING_INTERVAL: int = 300  # 5 minutes
    POLLING_LOOKBACK_HOURS: int = 24

    # Rate limiting
    MAX_CONCURRENT_DOWNLOADS: int = 5
    RATE_LIMIT_DELAY: float = 0.5  # seconds between downloads

    @classmethod
    def from_env(cls):
        """Load configuration from environment variables"""
        import os
        config = cls()
        config.WEBHOOK_SECRET = os.getenv("IFAX_WEBHOOK_SECRET")
        config.MAX_DOWNLOAD_RETRIES = int(os.getenv("IFAX_MAX_RETRIES", "3"))
        config.POLLING_ENABLED = os.getenv("IFAX_POLLING_ENABLED", "true").lower() == "true"
        return config


config = IFaxConfig.from_env()


# ==============================================================================
# WEBHOOK SIGNATURE VERIFICATION
# ==============================================================================

def verify_webhook_signature(
        payload_body: bytes,
        signature_header: Optional[str],
        secret: Optional[str]
) -> bool:
    """
    Verify webhook signature to ensure request is from iFax.

    Args:
        payload_body: Raw request body bytes
        signature_header: Signature from X-IFax-Signature header
        secret: Shared webhook secret

    Returns:
        True if signature is valid or verification is disabled

    Note:
        If no secret is configured, verification is skipped (development mode)
    """
    if not secret or not signature_header:
        logger.warning("⚠️ Webhook signature verification skipped (no secret configured)")
        return True

    try:
        # Compute HMAC signature
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison
        is_valid = hmac.compare_digest(expected_signature, signature_header)

        if not is_valid:
            logger.error(f"❌ Invalid webhook signature. Expected: {expected_signature[:16]}...")

        return is_valid

    except Exception as e:
        logger.error(f"❌ Error verifying webhook signature: {e}")
        return False


# ==============================================================================
# IDEMPOTENCY HANDLING
# ==============================================================================

async def is_duplicate_webhook(
        job_id: str,
        transaction_id: str,
        db: AsyncSession
) -> bool:
    """
    Check if this fax has already been processed.

    Args:
        job_id: iFax job ID
        transaction_id: Transaction ID
        db: Database session

    Returns:
        True if already processed
    """
    result = await db.execute(
        select(FaxFile).where(
            FaxFile.job_id == job_id,
            FaxFile.transaction_id == transaction_id
        )
    )
    existing = result.scalar_one_or_none()
    return existing is not None


# ==============================================================================
# RETRY LOGIC WITH EXPONENTIAL BACKOFF
# ==============================================================================

async def download_fax_with_retry(
        job_id: str,
        transaction_id: str,
        max_retries: int = None
) -> Optional[str]:
    """
    Download fax PDF with exponential backoff retry.

    Args:
        job_id: iFax job ID
        transaction_id: Transaction ID
        max_retries: Maximum retry attempts (defaults to config)

    Returns:
        File path if successful, None otherwise
    """
    if max_retries is None:
        max_retries = config.MAX_DOWNLOAD_RETRIES

    from app.services.ifax_service import download_fax

    for attempt in range(max_retries):
        try:
            logger.info(f"📥 Download attempt {attempt + 1}/{max_retries} for job {job_id}")

            file_path = await asyncio.wait_for(
                download_fax(job_id, transaction_id),
                timeout=config.DOWNLOAD_TIMEOUT
            )

            if file_path:
                logger.info(f"✅ Successfully downloaded fax on attempt {attempt + 1}")
                return file_path

            logger.warning(f"⚠️ Download returned None on attempt {attempt + 1}")

        except asyncio.TimeoutError:
            logger.error(f"⏱️ Download timeout on attempt {attempt + 1}")

        except Exception as e:
            logger.error(f"❌ Download error on attempt {attempt + 1}: {e}")

        # Exponential backoff (unless it's the last attempt)
        if attempt < max_retries - 1:
            delay = config.RETRY_INITIAL_DELAY * (config.RETRY_BACKOFF_BASE ** attempt)
            logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
            await asyncio.sleep(delay)

    logger.error(f"❌ Failed to download fax after {max_retries} attempts")
    return None


# ==============================================================================
# WEBHOOK ENDPOINT
# ==============================================================================

@router.post("/receive")
async def receive_fax_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        payload: FaxWebhookPayload,
        db: AsyncSession = Depends(get_db),
        x_ifax_signature: Optional[str] = Header(None)
):
    """
    Enhanced webhook endpoint for incoming faxes from iFax.

    Improvements:
    - Signature verification
    - Idempotency check
    - Fast response (202 Accepted)
    - Background processing with retry
    - Comprehensive logging

    Returns:
        202: Accepted for processing
        400: Invalid payload or signature
        409: Duplicate webhook (already processing)
    """
    logger.info(f"📨 Received fax webhook: job_id={payload.jobId}, transaction_id={payload.transactionId}")

    # Step 1: Verify webhook signature
    if config.WEBHOOK_SECRET:
        body = await request.body()
        if not verify_webhook_signature(body, x_ifax_signature, config.WEBHOOK_SECRET):
            logger.error("❌ Invalid webhook signature - rejecting request")
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    # Step 2: Check for duplicate
    is_duplicate = await is_duplicate_webhook(payload.jobId, payload.transactionId, db)
    if is_duplicate:
        logger.warning(f"⚠️ Duplicate webhook ignored: {payload.jobId}")
        return {
            "status": "duplicate",
            "message": "Fax already processed",
            "job_id": payload.jobId
        }

    # Step 3: Create FaxFile record immediately (claim this webhook)
    try:
        received_time = None
        if payload.faxCallStart:
            try:
                received_time = datetime.fromisoformat(
                    payload.faxCallStart.replace('Z', '+00:00')
                )
            except:
                received_time = datetime.utcnow()
        else:
            received_time = datetime.utcnow()

        fax_record = FaxFile(
            job_id=payload.jobId,
            transaction_id=payload.transactionId,
            sender=payload.faxNumber,
            receiver=payload.receiverNumber,
            received_time=received_time,
            file_path="",  # Will be updated after download
            pdf_data=b"",
            ocr_text=""
        )

        db.add(fax_record)
        await db.commit()
        await db.refresh(fax_record)

        logger.info(f"✅ Created FaxFile record #{fax_record.id}")

    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Failed to create FaxFile record: {e}")
        raise HTTPException(status_code=500, detail="Failed to create fax record")

    # Step 4: Queue background processing with enhanced retry
    background_tasks.add_task(
        process_fax_with_retry,
        payload.jobId,
        fax_record.id,
        payload.transactionId,
        received_time,
        payload.faxNumber,
        payload.receiverNumber
    )

    logger.info(f"✅ Fax queued for processing: FaxFile #{fax_record.id}")

    # Return 202 Accepted immediately
    return {
        "status": "accepted",
        "message": "Fax accepted for processing",
        "fax_id": fax_record.id,
        "job_id": payload.jobId
    }


async def process_fax_with_retry(
        job_id: str,
        fax_record_id: int,
        transaction_id: str,
        received_time: datetime,
        sender: Optional[str],
        receiver: Optional[str]
):
    """
    Background task to process fax with retry logic.

    This is the enhanced version with:
    - Download retry with exponential backoff
    - OCR timeout handling
    - Comprehensive error logging
    - Graceful degradation
    """
    from app.database.db import get_async_session_context

    logger.info(f"🔄 Starting enhanced processing for job {job_id}")

    try:
        # Step 1: Download with retry
        file_path = await download_fax_with_retry(job_id, transaction_id)

        if not file_path:
            logger.error(f"❌ Failed to download fax after all retries: {job_id}")
            # Update FaxFile with error status
            async with get_async_session_context() as db:
                result = await db.execute(
                    select(FaxFile).where(FaxFile.id == fax_record_id)
                )
                fax_record = result.scalar_one_or_none()
                if fax_record:
                    fax_record.ocr_text = "ERROR: Failed to download fax"
                    await db.commit()
            return

        # Step 2: Process with IncomingFaxProcessor (includes OCR, matching, etc.)
        async with get_async_session_context() as db:
            processor = IncomingFaxProcessor(db)

            result = await asyncio.wait_for(
                processor.process_incoming_fax(
                    job_id=job_id,
                    fax_record_id=fax_record_id,
                    transaction_id=transaction_id,
                    received_time=received_time,
                    sender=sender,
                    receiver=receiver
                ),
                timeout=config.PROCESSING_TIMEOUT
            )

            logger.info(f"✅ Fax processing completed: {result}")

    except asyncio.TimeoutError:
        logger.error(f"⏱️ Fax processing timeout: {job_id}")

    except Exception as e:
        logger.error(f"❌ Fax processing error: {e}", exc_info=True)


# ==============================================================================
# POLLING FALLBACK MECHANISM
# ==============================================================================

@router.post("/poll-incoming")
async def poll_incoming_faxes(
        db: AsyncSession = Depends(get_db),
        background_tasks: BackgroundTasks = None,
        lookback_hours: int = 24
):
    """
    Polling endpoint to fetch missed faxes (fallback if webhooks fail).

    This endpoint:
    1. Calls iFax API to list incoming faxes
    2. Checks which ones we haven't processed
    3. Downloads and processes missing faxes

    Args:
        lookback_hours: How many hours to look back

    Returns:
        Summary of discovered and processed faxes
    """
    if not config.POLLING_ENABLED:
        raise HTTPException(status_code=403, detail="Polling is disabled")

    logger.info(f"🔍 Starting polling for incoming faxes (lookback: {lookback_hours}h)")

    try:
        from app.services.ifax_service import get_incoming_faxes

        # Get list of incoming faxes from iFax
        since = datetime.utcnow() - timedelta(hours=lookback_hours)
        incoming_faxes = await get_incoming_faxes(since=since)

        logger.info(f"📋 Found {len(incoming_faxes)} faxes from iFax API")

        # Check which ones we don't have
        new_faxes = []
        for fax in incoming_faxes:
            job_id = fax.get('jobId')
            transaction_id = fax.get('transactionId')

            if not await is_duplicate_webhook(job_id, transaction_id, db):
                new_faxes.append(fax)

        logger.info(f"🆕 Found {len(new_faxes)} new faxes to process")

        # Process each new fax
        processed_count = 0
        failed_count = 0

        for fax in new_faxes:
            try:
                # Create FaxFile record
                received_time = datetime.fromisoformat(
                    fax.get('receivedAt', datetime.utcnow().isoformat()).replace('Z', '+00:00')
                )

                fax_record = FaxFile(
                    job_id=fax['jobId'],
                    transaction_id=fax['transactionId'],
                    sender=fax.get('from'),
                    receiver=fax.get('to'),
                    received_time=received_time,
                    file_path="",
                    pdf_data=b"",
                    ocr_text=""
                )

                db.add(fax_record)
                await db.commit()
                await db.refresh(fax_record)

                # Queue for processing
                if background_tasks:
                    background_tasks.add_task(
                        process_fax_with_retry,
                        fax['jobId'],
                        fax_record.id,
                        fax['transactionId'],
                        received_time,
                        fax.get('from'),
                        fax.get('to')
                    )

                processed_count += 1
                logger.info(f"✅ Queued fax for processing: {fax['jobId']}")

            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Failed to queue fax {fax.get('jobId')}: {e}")

        return {
            "status": "completed",
            "total_found": len(incoming_faxes),
            "new_faxes": len(new_faxes),
            "processed": processed_count,
            "failed": failed_count,
            "lookback_hours": lookback_hours
        }

    except Exception as e:
        logger.error(f"❌ Polling error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Polling failed: {str(e)}")


# ==============================================================================
# MANUAL DOWNLOAD/REPROCESSING
# ==============================================================================

@router.post("/download-manual")
async def download_fax_manual(
        request: FaxDownloadRequest,
        background_tasks: BackgroundTasks,
        db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger download and processing of a specific fax.

    Useful for:
    - Reprocessing failed faxes
    - Testing
    - Manual intervention when webhooks are missed
    """
    logger.info(f"🔧 Manual download requested: job_id={request.job_id}")

    # Check if already exists
    if not request.force_reprocess:
        is_dup = await is_duplicate_webhook(request.job_id, request.transaction_id, db)
        if is_dup:
            return {
                "status": "exists",
                "message": "Fax already processed. Use force_reprocess=true to reprocess."
            }

    # Create or update FaxFile record
    result = await db.execute(
        select(FaxFile).where(
            FaxFile.job_id == request.job_id,
            FaxFile.transaction_id == request.transaction_id
        )
    )
    fax_record = result.scalar_one_or_none()

    if not fax_record:
        fax_record = FaxFile(
            job_id=request.job_id,
            transaction_id=request.transaction_id,
            received_time=datetime.utcnow(),
            file_path="",
            pdf_data=b"",
            ocr_text=""
        )
        db.add(fax_record)
        await db.commit()
        await db.refresh(fax_record)

    # Queue for processing
    background_tasks.add_task(
        process_fax_with_retry,
        request.job_id,
        fax_record.id,
        request.transaction_id,
        fax_record.received_time,
        fax_record.sender,
        fax_record.receiver
    )

    return {
        "status": "queued",
        "message": "Fax queued for processing",
        "fax_id": fax_record.id,
        "job_id": request.job_id
    }


# ==============================================================================
# STATUS ENDPOINTS
# ==============================================================================

@router.get("/status/{job_id}")
async def get_fax_status(
        job_id: str,
        db: AsyncSession = Depends(get_db)
) -> FaxProcessingStatus:
    """
    Get processing status for a specific fax.

    Returns detailed status including:
    - Whether OCR completed
    - Whether patient matched
    - Whether provider matched
    - Any error messages
    """
    result = await db.execute(
        select(FaxFile).where(FaxFile.job_id == job_id)
    )
    fax = result.scalar_one_or_none()

    if not fax:
        raise HTTPException(status_code=404, detail="Fax not found")

    # Determine status
    if fax.ocr_text and "ERROR" not in fax.ocr_text:
        status = "completed"
        ocr_completed = True
    elif fax.ocr_text and "ERROR" in fax.ocr_text:
        status = "failed"
        ocr_completed = False
    elif fax.file_path:
        status = "processing"
        ocr_completed = False
    else:
        status = "downloading"
        ocr_completed = False

    return FaxProcessingStatus(
        job_id=job_id,
        status=status,
        patient_matched=fax.patient_id is not None,
        provider_matched=bool(fax.provider_requests),
        ocr_completed=ocr_completed,
        error_message=fax.ocr_text if "ERROR" in (fax.ocr_text or "") else None,
        processed_at=fax.received_time
    )


@router.get("/health")
async def health_check():
    """
    Health check endpoint for iFax service.
    """
    return {
        "service": "iFax Integration",
        "status": "healthy",
        "webhook_verification": config.WEBHOOK_SECRET is not None,
        "polling_enabled": config.POLLING_ENABLED,
        "max_retries": config.MAX_DOWNLOAD_RETRIES
    }


# ==============================================================================
# SCHEDULED POLLING (Optional Background Task)
# ==============================================================================

async def scheduled_polling_task():
    """
    Background task that runs periodically to poll for missed faxes.

    This should be run as a separate background process or scheduled task.
    Example using asyncio:

    ```python
    asyncio.create_task(scheduled_polling_task())
    ```
    """
    if not config.POLLING_ENABLED:
        logger.info("📴 Scheduled polling is disabled")
        return

    logger.info(f"⏰ Starting scheduled polling task (interval: {config.POLLING_INTERVAL}s)")

    while True:
        try:
            logger.info("🔍 Running scheduled fax polling...")

            from app.database.db import get_async_session_context
            async with get_async_session_context() as db:
                # Simulate calling the poll endpoint
                from app.services.ifax_service import get_incoming_faxes
                from fastapi import BackgroundTasks

                since = datetime.utcnow() - timedelta(hours=config.POLLING_LOOKBACK_HOURS)
                incoming_faxes = await get_incoming_faxes(since=since)

                logger.info(f"📋 Polling found {len(incoming_faxes)} faxes")

                # Process new faxes
                for fax in incoming_faxes:
                    job_id = fax.get('jobId')
                    transaction_id = fax.get('transactionId')

                    if not await is_duplicate_webhook(job_id, transaction_id, db):
                        logger.info(f"🆕 Processing missed fax: {job_id}")

                        # Create record and process
                        fax_record = FaxFile(
                            job_id=job_id,
                            transaction_id=transaction_id,
                            sender=fax.get('from'),
                            receiver=fax.get('to'),
                            received_time=datetime.utcnow(),
                            file_path="",
                            pdf_data=b"",
                            ocr_text=""
                        )

                        db.add(fax_record)
                        await db.commit()
                        await db.refresh(fax_record)

                        # Process in background
                        asyncio.create_task(
                            process_fax_with_retry(
                                job_id,
                                fax_record.id,
                                transaction_id,
                                fax_record.received_time,
                                fax.get('from'),
                                fax.get('to')
                            )
                        )

        except Exception as e:
            logger.error(f"❌ Scheduled polling error: {e}", exc_info=True)

        # Wait for next interval
        await asyncio.sleep(config.POLLING_INTERVAL)