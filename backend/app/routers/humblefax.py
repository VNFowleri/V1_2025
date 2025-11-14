# app/routers/humblefax.py
"""
HumbleFax Webhook Router

Handles incoming webhooks from HumbleFax API for:
1. Inbound faxes (incoming medical records)
2. Outbound fax status updates (delivery confirmations)

Note: HumbleFax webhook configuration is done through their dashboard at:
https://app.humblefax.com/?category=developer-settings

You need to configure webhook URLs in the HumbleFax dashboard for:
- Incoming Faxes: https://your-domain.com/humblefax/receive
- Outgoing Faxes: https://your-domain.com/humblefax/outbound-status

Key differences from iFax:
- HumbleFax uses simpler webhook payloads
- File data may be included directly in webhook or require separate download
- Status updates use different field names
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
import logging
from pydantic import BaseModel, Field
from typing import Optional
import base64

from app.database.db import get_db, AsyncSessionLocal
from app.models import FaxFile, ProviderRequest
from app.services.fax_processor import process_incoming_fax

router = APIRouter()
logger = logging.getLogger(__name__)


class HumbleFaxInboundPayload(BaseModel):
    """
    HumbleFax webhook payload structure for incoming faxes.
    
    Based on typical fax service patterns. Actual payload may vary.
    Configure webhooks in HumbleFax dashboard.
    
    Example payload (estimated structure):
    {
        "id": "abc123",
        "from": "+15551234567",
        "to": "+15559876543",
        "pages": 5,
        "received_at": "2024-01-15T10:30:00Z",
        "status": "received",
        "file": "base64_encoded_pdf_data" or URL
    }
    """
    id: str  # Fax ID
    from_number: Optional[str] = Field(None, alias="from")
    to: Optional[str] = None
    pages: Optional[int] = None
    received_at: Optional[str] = None
    status: Optional[str] = None
    file: Optional[str] = None  # Could be base64 or URL
    file_url: Optional[str] = None
    
    class Config:
        extra = "allow"  # Allow additional fields
        populate_by_name = True


class HumbleFaxOutboundPayload(BaseModel):
    """
    HumbleFax webhook payload for outbound fax status updates.
    
    Example payload (estimated structure):
    {
        "id": "tmpfax123",
        "status": "success" or "failed",
        "to": "+15551234567",
        "completed_at": "2024-01-15T10:35:00Z",
        "error": "Error message if failed"
    }
    """
    id: str  # Temp fax ID
    status: str
    to: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    
    class Config:
        extra = "allow"


@router.post("/receive")
async def receive_fax_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        db: AsyncSession = Depends(get_db)
):
    """
    Webhook endpoint for receiving incoming faxes from HumbleFax.
    
    Configure this URL in your HumbleFax dashboard under:
    Developer Settings > Webhooks > Incoming Fax Webhook
    
    This endpoint:
    1. Validates the webhook payload
    2. Creates a FaxFile database record immediately
    3. Handles the PDF file (download if URL, decode if base64)
    4. Queues background processing for:
       - OCR text extraction
       - Patient matching
       - Provider request matching
       - Aggregation when complete
    
    Returns immediately with 200 OK to HumbleFax.
    """
    logger.info("=" * 80)
    logger.info("📨 Incoming fax webhook received from HumbleFax")
    logger.info(f"Headers: {dict(request.headers)}")
    
    try:
        payload_data = await request.json()
        logger.info(f"Raw payload: {payload_data}")
        
        # Validate payload structure
        payload = HumbleFaxInboundPayload(**payload_data)
        logger.info(
            f"✅ Valid payload: FaxID={payload.id}, "
            f"From={payload.from_number}, "
            f"Pages={payload.pages}"
        )
        
    except ValueError as e:
        logger.error(f"❌ Invalid payload structure: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error parsing payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Parse received time
    try:
        if payload.received_at:
            received_time = datetime.fromisoformat(payload.received_at.replace('Z', '+00:00'))
        else:
            received_time = datetime.utcnow()
    except Exception as e:
        logger.warning(f"Could not parse received_at: {e}, using current time")
        received_time = datetime.utcnow()
    
    # Handle PDF file
    pdf_data = b""
    file_path = ""
    
    try:
        if payload.file:
            # File data included in webhook (likely base64)
            try:
                # Try to decode as base64
                pdf_data = base64.b64decode(payload.file)
                logger.info(f"✅ Decoded PDF from base64 ({len(pdf_data)} bytes)")
            except Exception as e:
                logger.warning(f"Could not decode file as base64: {e}")
                # Might be a URL instead
                if payload.file.startswith('http'):
                    logger.info(f"File appears to be URL: {payload.file}")
                    # Will download in background processing
        
        elif payload.file_url:
            # File available via URL - will download in background
            logger.info(f"File available at URL: {payload.file_url}")
            
        else:
            logger.warning("No file data or URL in payload")
    
    except Exception as e:
        logger.exception(f"Error handling file data: {e}")
    
    # Create FaxFile record immediately
    try:
        fax = FaxFile(
            job_id=payload.id,  # Use HumbleFax ID as job_id
            transaction_id=payload.id,  # Use same ID for transaction
            sender=payload.from_number or "",
            receiver=payload.to or "",
            received_time=received_time,
            file_path=file_path,
            pdf_data=pdf_data,
            ocr_text="",  # Will be populated during processing
        )
        
        db.add(fax)
        await db.commit()
        await db.refresh(fax)
        
        logger.info(
            f"✅ Created FaxFile record: ID={fax.id}, HumbleFaxID={payload.id}"
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
        fax_id=payload.id,
        fax_record_id=fax.id,
        file_url=payload.file_url
    )
    
    logger.info(
        f"✅ Queued background processing for FaxID={fax.id}, HumbleFaxID={payload.id}"
    )
    logger.info("=" * 80)
    
    # Return success immediately (don't make HumbleFax wait)
    return {
        "status": "ok",
        "message": "Fax received and queued for processing",
        "fax_id": fax.id,
        "humblefax_id": payload.id
    }


async def process_fax_background(
        fax_id: str,
        fax_record_id: int,
        file_url: Optional[str] = None
):
    """
    Background task for processing incoming fax.
    
    This runs asynchronously after the webhook returns 200 OK.
    Handles the complete processing pipeline:
    - Download PDF (if URL provided)
    - OCR extraction
    - Patient matching
    - Provider matching
    - Request completion and PDF compilation
    """
    logger.info(f"🚀 Starting background processing for FaxID={fax_record_id}")
    
    try:
        # Use a new database session for background processing
        async with AsyncSessionLocal() as db:
            # Get the fax record
            result = await db.execute(
                select(FaxFile).where(FaxFile.id == fax_record_id)
            )
            fax = result.scalars().first()
            
            if not fax:
                logger.error(f"FaxFile {fax_record_id} not found")
                return
            
            # If we need to download the file
            if file_url and not fax.pdf_data:
                logger.info(f"Downloading PDF from: {file_url}")
                try:
                    import requests
                    r = requests.get(file_url, timeout=60)
                    if r.status_code == 200:
                        fax.pdf_data = r.content
                        
                        # Also save to file system
                        import os
                        out_dir = os.path.join(os.getcwd(), "received_faxes")
                        os.makedirs(out_dir, exist_ok=True)
                        file_path = os.path.join(out_dir, f"{fax_id}.pdf")
                        
                        with open(file_path, "wb") as f:
                            f.write(fax.pdf_data)
                        
                        fax.file_path = file_path
                        await db.commit()
                        logger.info(f"✅ Downloaded and saved PDF: {file_path}")
                    else:
                        logger.error(f"Failed to download PDF: {r.status_code}")
                except Exception as e:
                    logger.exception(f"Error downloading PDF: {e}")
            
            # Save PDF to file if not already saved
            if fax.pdf_data and not fax.file_path:
                import os
                out_dir = os.path.join(os.getcwd(), "received_faxes")
                os.makedirs(out_dir, exist_ok=True)
                file_path = os.path.join(out_dir, f"{fax_id}.pdf")
                
                with open(file_path, "wb") as f:
                    f.write(fax.pdf_data)
                
                fax.file_path = file_path
                await db.commit()
                logger.info(f"✅ Saved PDF to: {file_path}")
            
            # Now run the standard fax processing
            result = await process_incoming_fax(
                job_id=fax_id,
                fax_record_id=fax_record_id,
                transaction_id=fax_id,  # Use same ID
                db=db,
                direction="inbound"
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
    Webhook endpoint for outbound fax status updates from HumbleFax.
    
    Configure this URL in your HumbleFax dashboard under:
    Developer Settings > Webhooks > Outgoing Fax Webhook
    
    This endpoint receives status updates for faxes we sent out:
    - success/delivered: Fax successfully delivered to recipient
    - failed: Fax delivery failed
    
    Updates the corresponding ProviderRequest status in our database.
    """
    logger.info("📤 Outbound fax status webhook received from HumbleFax")
    
    try:
        payload = await request.json()
        logger.info(f"Status payload: {payload}")
        
        # Parse payload
        status_data = HumbleFaxOutboundPayload(**payload)
        
        tmp_fax_id = status_data.id
        status = status_data.status.lower()
        error_message = status_data.error or ""
        
        if not tmp_fax_id:
            logger.warning("⚠️ No fax ID in outbound status payload")
            return {"status": "ok", "message": "No fax ID provided"}
        
        # Find the ProviderRequest with this tmp_fax_id
        # Note: We store the tmpFaxId in outbound_job_id field
        result = await db.execute(
            select(ProviderRequest).where(
                ProviderRequest.outbound_job_id == tmp_fax_id
            )
        )
        provider_request = result.scalars().first()
        
        if not provider_request:
            logger.warning(
                f"⚠️ No ProviderRequest found for TmpFaxID={tmp_fax_id}"
            )
            return {"status": "ok", "message": f"No request found for fax ID {tmp_fax_id}"}
        
        # Update status based on HumbleFax status
        old_status = provider_request.status
        
        if status in ("success", "delivered", "completed", "sent"):
            provider_request.status = "fax_delivered"
            provider_request.delivered_at = datetime.utcnow()
            logger.info(
                f"✅ Fax delivered: ProviderRequest={provider_request.id}, "
                f"TmpFaxID={tmp_fax_id}"
            )
        
        elif status in ("failed", "error", "failure"):
            provider_request.status = "fax_failed"
            provider_request.failed_reason = error_message
            logger.warning(
                f"❌ Fax failed: ProviderRequest={provider_request.id}, "
                f"TmpFaxID={tmp_fax_id}, Reason={error_message}"
            )
        
        elif status in ("queued", "pending", "processing"):
            # Fax is still in progress - keep as fax_sent
            logger.info(
                f"📋 Fax in progress: ProviderRequest={provider_request.id}, "
                f"TmpFaxID={tmp_fax_id}, Status={status}"
            )
            return {"status": "ok", "message": f"Fax status: {status}"}
        
        else:
            # Unknown status, log but don't update
            logger.warning(
                f"⚠️ Unknown status '{status}' for TmpFaxID={tmp_fax_id}"
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
            "new_status": provider_request.status
        }
    
    except Exception as e:
        logger.exception(f"Error processing outbound status webhook: {e}")
        # Return 200 OK even on error to prevent webhook retries
        return {"status": "error", "message": str(e)}


@router.get("/status/{fax_id}")
async def get_fax_status(
        fax_id: int,
        db: AsyncSession = Depends(get_db)
):
    """
    Get the processing status of a specific fax.
    
    Useful for debugging and monitoring fax processing.
    """
    result = await db.execute(
        select(FaxFile).where(FaxFile.id == fax_id)
    )
    fax = result.scalars().first()
    
    if not fax:
        raise HTTPException(status_code=404, detail="Fax not found")
    
    return {
        "fax_id": fax.id,
        "job_id": fax.job_id,
        "sender": fax.sender,
        "receiver": fax.receiver,
        "received_time": fax.received_time,
        "has_pdf": bool(fax.pdf_data),
        "has_ocr": bool(fax.ocr_text),
        "patient_id": fax.patient_id,
        "encounter_date": fax.encounter_date
    }


@router.get("/health")
async def health_check():
    """Health check endpoint for HumbleFax service"""
    import os
    
    has_credentials = bool(
        os.getenv("HUMBLEFAX_ACCESS_KEY") and 
        os.getenv("HUMBLEFAX_SECRET_KEY")
    )
    
    return {
        "service": "HumbleFax",
        "status": "ok",
        "credentials_configured": has_credentials
    }
