#!/usr/bin/env python3
"""
Reprocess Failed Faxes

This script finds faxes that failed OCR processing and attempts to reprocess them.
Useful after fixing OCR setup issues.

Usage:
    python reprocess_faxes.py [--all] [--fax-id ID]
    
Options:
    --all         Reprocess all faxes with missing or failed OCR
    --fax-id ID   Reprocess specific fax by job_id
"""

import asyncio
import sys
import os
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database.db import async_session_maker
from app.models.fax_file import FaxFile
from app.services.ocr_service import extract_text_from_pdf, is_ocr_available
from app.services.fax_processor import IncomingFaxProcessor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def reprocess_fax(fax_id: int):
    """
    Reprocess a single fax.
    
    Args:
        fax_id: Database ID of FaxFile record
    """
    async with async_session_maker() as db:
        # Get fax record
        result = await db.execute(
            select(FaxFile).where(FaxFile.id == fax_id)
        )
        fax_file = result.scalar_one_or_none()
        
        if not fax_file:
            logger.error(f"❌ FaxFile #{fax_id} not found")
            return False
        
        logger.info(f"🔄 Reprocessing FaxFile #{fax_id} (job_id: {fax_file.job_id})")
        
        # Check if PDF file exists
        if not fax_file.file_path or not os.path.exists(fax_file.file_path):
            logger.error(f"❌ PDF file not found: {fax_file.file_path}")
            return False
        
        try:
            # Run OCR
            logger.info(f"📄 Running OCR on {fax_file.file_path}...")
            ocr_text = extract_text_from_pdf(fax_file.file_path)
            
            if not ocr_text or len(ocr_text.strip()) == 0:
                logger.error("❌ OCR returned empty text")
                return False
            
            logger.info(f"✅ OCR extracted {len(ocr_text)} characters")
            
            # Update fax record
            fax_file.ocr_text = ocr_text
            await db.commit()
            
            # Process with fax processor
            logger.info("🔍 Processing fax content...")
            processor = IncomingFaxProcessor(db)
            success = await processor.process_incoming_fax(
                job_id=fax_file.job_id,
                fax_file=fax_file
            )
            
            if success:
                logger.info(f"✅ Successfully reprocessed FaxFile #{fax_id}")
            else:
                logger.warning(f"⚠️ Reprocessing completed but matching may have failed")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Error reprocessing fax: {str(e)}", exc_info=True)
            return False


async def find_failed_faxes():
    """
    Find all faxes that failed OCR processing.
    
    Returns:
        List of FaxFile IDs
    """
    async with async_session_maker() as db:
        # Find faxes with empty or error OCR text
        result = await db.execute(
            select(FaxFile).where(
                (FaxFile.ocr_text == "") |
                (FaxFile.ocr_text.like("[OCR%")) |
                (FaxFile.ocr_text == None)
            ).order_by(FaxFile.id.desc())
        )
        failed_faxes = result.scalars().all()
        
        return [fax.id for fax in failed_faxes]


async def reprocess_all():
    """
    Reprocess all faxes that failed OCR.
    """
    logger.info("🔍 Finding failed faxes...")
    
    failed_ids = await find_failed_faxes()
    
    if not failed_ids:
        logger.info("✅ No failed faxes found!")
        return
    
    logger.info(f"Found {len(failed_ids)} fax(es) to reprocess")
    
    # Process each fax
    success_count = 0
    failure_count = 0
    
    for i, fax_id in enumerate(failed_ids, 1):
        logger.info(f"\n{'=' * 70}")
        logger.info(f"Processing {i}/{len(failed_ids)}")
        logger.info(f"{'=' * 70}")
        
        success = await reprocess_fax(fax_id)
        
        if success:
            success_count += 1
        else:
            failure_count += 1
        
        # Small delay between faxes
        await asyncio.sleep(1)
    
    logger.info(f"\n{'=' * 70}")
    logger.info(f"SUMMARY")
    logger.info(f"{'=' * 70}")
    logger.info(f"Total processed: {len(failed_ids)}")
    logger.info(f"✅ Successful: {success_count}")
    logger.info(f"❌ Failed: {failure_count}")


async def reprocess_by_job_id(job_id: str):
    """
    Reprocess a fax by its job_id (HumbleFax ID).
    """
    async with async_session_maker() as db:
        result = await db.execute(
            select(FaxFile).where(FaxFile.job_id == job_id)
        )
        fax_file = result.scalar_one_or_none()
        
        if not fax_file:
            logger.error(f"❌ No fax found with job_id: {job_id}")
            return False
        
        logger.info(f"Found FaxFile #{fax_file.id} with job_id {job_id}")
        return await reprocess_fax(fax_file.id)


def main():
    # Check OCR is available
    if not is_ocr_available():
        logger.error("❌ OCR service not available!")
        logger.error("Please install dependencies:")
        logger.error("  brew install tesseract poppler")
        logger.error("  pip install Pillow")
        return 1
    
    logger.info("✅ OCR service is available")
    
    # Parse arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--all":
            logger.info("Reprocessing ALL failed faxes...")
            asyncio.run(reprocess_all())
        elif sys.argv[1] == "--fax-id" and len(sys.argv) > 2:
            job_id = sys.argv[2]
            logger.info(f"Reprocessing fax with job_id: {job_id}...")
            asyncio.run(reprocess_by_job_id(job_id))
        else:
            print("Usage:")
            print(f"  {sys.argv[0]} --all              # Reprocess all failed faxes")
            print(f"  {sys.argv[0]} --fax-id ID        # Reprocess specific fax")
            return 1
    else:
        # Interactive mode
        print("Reprocess Failed Faxes")
        print("=" * 70)
        print()
        print("Options:")
        print("  1) Reprocess all failed faxes")
        print("  2) Reprocess specific fax by job_id")
        print("  q) Quit")
        print()
        
        choice = input("Enter choice: ").strip()
        
        if choice == "1":
            asyncio.run(reprocess_all())
        elif choice == "2":
            job_id = input("Enter fax job_id: ").strip()
            asyncio.run(reprocess_by_job_id(job_id))
        elif choice.lower() == "q":
            return 0
        else:
            print("Invalid choice")
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
