"""
Medical Records Compilation Service

Service for compiling all medical records for a patient into a single PDF,
ordered chronologically by clinical encounter date.
"""

import os
import asyncio
import tempfile
import logging
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.fax_file import FaxFile
from app.models.patient import Patient
from app.services.pdf_ops import ocr_to_searchable_pdf, merge_pdfs

logger = logging.getLogger(__name__)


async def compile_all_patient_records(
    patient_id: int,
    db: AsyncSession,
    output_filename: Optional[str] = None
) -> Optional[str]:
    """
    Compile ALL medical records for a patient into a single searchable PDF,
    ordered chronologically by encounter date (oldest first).
    
    This function:
    1. Retrieves all fax files for the patient
    2. Orders them by encounter_date (with fallback to received_time)
    3. Converts each to searchable PDF
    4. Merges into a single PDF
    5. Saves to storage directory
    
    Args:
        patient_id: ID of the patient
        db: Database session
        output_filename: Optional custom filename (default: patient_{id}_all_records_{timestamp}.pdf)
        
    Returns:
        Absolute path to compiled PDF, or None if compilation failed
    """
    logger.info(f"📚 Starting compilation of all records for patient {patient_id}")
    
    # Get patient info
    patient = await db.get(Patient, patient_id)
    if not patient:
        logger.error(f"Patient {patient_id} not found")
        return None
    
    # Get ALL fax files for this patient
    result = await db.execute(
        select(FaxFile).where(FaxFile.patient_id == patient_id)
    )
    fax_files = result.scalars().all()
    
    if not fax_files:
        logger.warning(f"No fax files found for patient {patient_id}")
        return None
    
    logger.info(f"Found {len(fax_files)} fax file(s) for patient {patient_id}")
    
    # Sort by encounter date (oldest first), with fallback to received_time
    # This ensures records are in chronological order by when services were provided
    def sort_key(fax):
        if fax.encounter_date:
            # Use encounter date if available (preferred)
            return (0, fax.encounter_date, fax.received_time)
        else:
            # Fallback to received_time if no encounter date
            # Use a high priority (1) so these come after dated records
            return (1, fax.received_time.date() if fax.received_time else datetime.now().date(), fax.received_time)
    
    sorted_faxes = sorted(fax_files, key=sort_key)
    
    # Log the sorting order for debugging
    logger.info("📅 Records will be compiled in this order:")
    for i, fax in enumerate(sorted_faxes, 1):
        date_info = f"Encounter: {fax.encounter_date}" if fax.encounter_date else f"Received: {fax.received_time.date()}"
        logger.info(f"  {i}. Fax ID={fax.id}, {date_info}")
    
    # Create temporary directory for processing
    tmpdir = tempfile.mkdtemp()
    searchable_pdfs = []
    
    try:
        # Convert each fax to searchable PDF
        for fax in sorted_faxes:
            if not fax.file_path or not os.path.exists(fax.file_path):
                logger.warning(f"Fax {fax.id} missing file, skipping")
                continue
            
            # Create searchable PDF
            searchable_path = os.path.join(tmpdir, f"searchable_{fax.id}.pdf")
            
            try:
                await asyncio.to_thread(
                    ocr_to_searchable_pdf,
                    fax.file_path,
                    searchable_path
                )
                searchable_pdfs.append(searchable_path)
                logger.debug(f"✅ Created searchable PDF for fax {fax.id}")
            except Exception as e:
                logger.warning(
                    f"Failed to create searchable PDF for fax {fax.id}: {e}, "
                    "using original"
                )
                searchable_pdfs.append(fax.file_path)
        
        if not searchable_pdfs:
            logger.error("No PDFs available to merge")
            return None
        
        # Generate output filename
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"patient_{patient_id}_all_records_{timestamp}.pdf"
        
        # Ensure storage directory exists
        os.makedirs("storage", exist_ok=True)
        final_path = os.path.join("storage", output_filename)
        
        # Merge all PDFs in chronological order
        logger.info(f"🔗 Merging {len(searchable_pdfs)} PDFs into: {final_path}")
        await asyncio.to_thread(merge_pdfs, searchable_pdfs, final_path)
        
        logger.info(
            f"✅ Successfully compiled {len(searchable_pdfs)} record(s) for patient {patient_id}"
        )
        logger.info(f"   Output: {final_path}")
        logger.info(f"   Ordered by encounter date (oldest → newest)")
        
        return os.path.abspath(final_path)
    
    except Exception as e:
        logger.exception(f"Failed to compile patient records: {e}")
        return None
    
    finally:
        # Cleanup temporary directory
        try:
            import shutil
            shutil.rmtree(tmpdir)
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory {tmpdir}: {e}")


async def get_patient_records_summary(
    patient_id: int,
    db: AsyncSession
) -> dict:
    """
    Get a summary of all medical records for a patient.
    
    Returns:
        Dictionary with:
        - total_records: Number of fax files
        - records_with_encounter_date: Number with encounter date
        - date_range: Earliest and latest encounter dates
        - records: List of record summaries
    """
    result = await db.execute(
        select(FaxFile).where(FaxFile.patient_id == patient_id)
    )
    fax_files = result.scalars().all()
    
    if not fax_files:
        return {
            "total_records": 0,
            "records_with_encounter_date": 0,
            "date_range": None,
            "records": []
        }
    
    records_with_dates = [f for f in fax_files if f.encounter_date]
    
    # Find date range
    date_range = None
    if records_with_dates:
        encounter_dates = [f.encounter_date for f in records_with_dates]
        date_range = {
            "earliest": min(encounter_dates),
            "latest": max(encounter_dates)
        }
    
    # Create record summaries
    records = []
    for fax in fax_files:
        records.append({
            "id": fax.id,
            "received_time": fax.received_time,
            "encounter_date": fax.encounter_date,
            "sender": fax.sender,
            "has_file": bool(fax.file_path and os.path.exists(fax.file_path))
        })
    
    return {
        "total_records": len(fax_files),
        "records_with_encounter_date": len(records_with_dates),
        "date_range": date_range,
        "records": records
    }


# Example usage
if __name__ == "__main__":
    import asyncio
    from app.database.db import get_async_session
    
    async def test_compile():
        async with get_async_session() as db:
            # Test compilation
            patient_id = 1  # Replace with actual patient ID
            
            # Get summary first
            summary = await get_patient_records_summary(patient_id, db)
            print(f"\nPatient Records Summary:")
            print(f"  Total Records: {summary['total_records']}")
            print(f"  With Encounter Date: {summary['records_with_encounter_date']}")
            if summary['date_range']:
                print(f"  Date Range: {summary['date_range']['earliest']} to {summary['date_range']['latest']}")
            
            # Compile all records
            print(f"\nCompiling all records...")
            result_path = await compile_all_patient_records(patient_id, db)
            
            if result_path:
                print(f"✅ Success: {result_path}")
            else:
                print(f"❌ Failed to compile records")
    
    asyncio.run(test_compile())
