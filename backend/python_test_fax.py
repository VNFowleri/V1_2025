# test_fax_processing.py
"""
Testing Script for Incoming Fax Processing

This script allows you to test the fax processing pipeline with sample data
without needing actual faxes from iFax.

Usage:
    python test_fax_processing.py
"""

import asyncio
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, date
import logging

from app.database.db import AsyncSessionLocal
from app.models import Patient, Provider, RecordRequest, ProviderRequest, FaxFile
from app.services.fax_processor import IncomingFaxProcessor
from app.utils.ocr import parse_name_and_dob, parse_with_confidence

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Sample OCR text from a typical medical records fax
SAMPLE_OCR_TEXT_1 = """
MASSACHUSETTS GENERAL HOSPITAL
Medical Records Department
55 Fruit Street
Boston, MA 02114

PATIENT MEDICAL RECORDS

Patient Name: John Michael Smith
Date of Birth: 03/15/1980
Medical Record #: MRN-123456789

Date of Request: November 10, 2025

The following records are being sent in response to your authorization request:
- Office visit notes (2023-2025)
- Laboratory results
- Imaging reports
- Medication history

Total Pages: 15

For questions, please contact our Medical Records Department:
Phone: (617) 726-2000
Fax: (617) 726-2001

This information is confidential and protected under HIPAA.
"""

SAMPLE_OCR_TEXT_2 = """
BRIGHAM AND WOMEN'S HOSPITAL
Health Information Management Department

Smith, Jane Elizabeth
DOB: 08/22/1975
MRN: BWH-987654321

Medical Records Release

Enclosed are the requested medical records for the above patient,
including:

- Complete history and physical
- Progress notes from 01/2024 to 11/2025
- Diagnostic test results
- Discharge summaries

Page 1 of 20

Contact: HIM Department
Fax: (617) 732-5500
"""


async def create_test_patient(db: AsyncSession, first_name: str, last_name: str, dob: date):
    """Create a test patient in the database."""

    # Check if patient already exists
    result = await db.execute(
        select(Patient).where(
            Patient.first_name == first_name,
            Patient.last_name == last_name,
            Patient.date_of_birth == dob
        )
    )
    existing = result.scalars().first()

    if existing:
        logger.info(f"Patient already exists: {existing.id}")
        return existing

    # Create new patient
    patient = Patient(
        first_name=first_name,
        last_name=last_name,
        email=f"{first_name.lower()}.{last_name.lower()}@example.com",
        phone="+1-555-0100",
        date_of_birth=dob
    )

    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    logger.info(f"Created patient: ID={patient.id}, Name={first_name} {last_name}")
    return patient


async def create_test_provider(db: AsyncSession, name: str, fax: str):
    """Create a test provider in the database."""

    # Check if provider already exists
    result = await db.execute(
        select(Provider).where(Provider.fax == fax)
    )
    existing = result.scalars().first()

    if existing:
        logger.info(f"Provider already exists: {existing.id}")
        return existing

    # Create new provider
    provider = Provider(
        name=name,
        fax=fax,
        city="Boston",
        state="MA",
        phone="+1-555-0200",
        source="test"
    )

    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    logger.info(f"Created provider: ID={provider.id}, Name={name}")
    return provider


async def create_test_record_request(
        db: AsyncSession,
        patient_id: int,
        provider_id: int,
        provider_fax: str
):
    """Create a test record request and provider request."""

    # Create RecordRequest
    record_request = RecordRequest(
        patient_id=patient_id,
        status="in_progress",
        requested_cities="Boston",
        release_pdf_path="/fake/path/release.pdf"
    )

    db.add(record_request)
    await db.commit()
    await db.refresh(record_request)

    logger.info(f"Created record request: ID={record_request.id}")

    # Create ProviderRequest
    provider_request = ProviderRequest(
        record_request_id=record_request.id,
        provider_id=provider_id,
        fax_number_used=provider_fax,
        status="fax_sent",
        outbound_job_id="test-job-123"
    )

    db.add(provider_request)
    await db.commit()
    await db.refresh(provider_request)

    logger.info(f"Created provider request: ID={provider_request.id}")

    return record_request, provider_request


async def create_test_fax(
        db: AsyncSession,
        sender_fax: str,
        ocr_text: str
):
    """Create a test fax file entry."""

    fax = FaxFile(
        job_id=f"test-job-{datetime.now().timestamp()}",
        transaction_id="test-trans-123",
        sender=sender_fax,
        receiver="+1-555-9999",
        received_time=datetime.utcnow(),
        file_path="/fake/path/fax.pdf",
        pdf_data=b"fake pdf data",
        ocr_text=ocr_text
    )

    db.add(fax)
    await db.commit()
    await db.refresh(fax)

    logger.info(f"Created test fax: ID={fax.id}")
    return fax


async def test_ocr_parsing():
    """Test OCR text parsing functions."""
    logger.info("=" * 80)
    logger.info("TEST 1: OCR Text Parsing")
    logger.info("=" * 80)

    print("\n--- Sample OCR Text 1 ---")
    print(SAMPLE_OCR_TEXT_1[:200] + "...")

    result1 = parse_with_confidence(SAMPLE_OCR_TEXT_1)
    print(f"\nParsed Results:")
    print(f"  First Name: {result1['first_name']}")
    print(f"  Last Name: {result1['last_name']}")
    print(f"  DOB: {result1['dob']}")
    print(f"  Confidence: {result1['confidence']:.2%}")

    print("\n--- Sample OCR Text 2 ---")
    print(SAMPLE_OCR_TEXT_2[:200] + "...")

    result2 = parse_with_confidence(SAMPLE_OCR_TEXT_2)
    print(f"\nParsed Results:")
    print(f"  First Name: {result2['first_name']}")
    print(f"  Last Name: {result2['last_name']}")
    print(f"  DOB: {result2['dob']}")
    print(f"  Confidence: {result2['confidence']:.2%}")


async def test_patient_matching():
    """Test patient matching logic."""
    logger.info("=" * 80)
    logger.info("TEST 2: Patient Matching")
    logger.info("=" * 80)

    async with AsyncSessionLocal() as db:
        # Create test patient
        patient = await create_test_patient(
            db,
            first_name="John",
            last_name="Smith",
            dob=date(1980, 3, 15)
        )

        # Create test fax with OCR text
        fax = await create_test_fax(
            db,
            sender_fax="+1-617-726-2001",
            ocr_text=SAMPLE_OCR_TEXT_1
        )

        # Test matching
        processor = IncomingFaxProcessor(db)
        match_result = await processor._match_patient(SAMPLE_OCR_TEXT_1, fax.id)

        print(f"\nPatient Matching Results:")
        print(f"  Matched: {match_result['matched']}")
        print(f"  Patient ID: {match_result['patient_id']}")
        print(f"  Name: {match_result['name']}")
        print(f"  Confidence: {match_result['confidence']:.2%}")
        print(f"  Method: {match_result['match_method']}")

        if match_result['matched']:
            print(f"\n✅ Successfully matched to patient {patient.id}!")
        else:
            print(f"\n❌ Failed to match patient")


async def test_provider_matching():
    """Test provider request matching logic."""
    logger.info("=" * 80)
    logger.info("TEST 3: Provider Request Matching")
    logger.info("=" * 80)

    async with AsyncSessionLocal() as db:
        # Create test data
        patient = await create_test_patient(
            db,
            first_name="John",
            last_name="Smith",
            dob=date(1980, 3, 15)
        )

        provider = await create_test_provider(
            db,
            name="Massachusetts General Hospital",
            fax="+1-617-726-2001"
        )

        record_request, provider_request = await create_test_record_request(
            db,
            patient_id=patient.id,
            provider_id=provider.id,
            provider_fax=provider.fax
        )

        # Create test fax
        fax = await create_test_fax(
            db,
            sender_fax="+1-617-726-2001",
            ocr_text=SAMPLE_OCR_TEXT_1
        )

        # Test provider matching
        processor = IncomingFaxProcessor(db)
        matched_ids = await processor._match_provider_requests(
            patient_id=patient.id,
            sender_fax=fax.sender,
            fax_id=fax.id,
            ocr_text=SAMPLE_OCR_TEXT_1
        )

        print(f"\nProvider Matching Results:")
        print(f"  Matched Provider Requests: {len(matched_ids)}")
        print(f"  Provider Request IDs: {matched_ids}")

        if matched_ids:
            # Verify status was updated
            await db.refresh(provider_request)
            print(f"  Provider Request Status: {provider_request.status}")
            print(f"  Inbound Fax ID: {provider_request.inbound_fax_id}")
            print(f"\n✅ Successfully matched to provider request!")
        else:
            print(f"\n❌ Failed to match provider request")


async def test_full_pipeline():
    """Test the complete fax processing pipeline."""
    logger.info("=" * 80)
    logger.info("TEST 4: Complete Processing Pipeline")
    logger.info("=" * 80)

    async with AsyncSessionLocal() as db:
        # Create test data
        patient = await create_test_patient(
            db,
            first_name="John",
            last_name="Smith",
            dob=date(1980, 3, 15)
        )

        provider = await create_test_provider(
            db,
            name="Massachusetts General Hospital",
            fax="+1-617-726-2001"
        )

        record_request, provider_request = await create_test_record_request(
            db,
            patient_id=patient.id,
            provider_id=provider.id,
            provider_fax=provider.fax
        )

        # Create test fax
        fax = await create_test_fax(
            db,
            sender_fax="+1-617-726-2001",
            ocr_text=SAMPLE_OCR_TEXT_1
        )

        # Process through pipeline (without actual download/OCR steps)
        processor = IncomingFaxProcessor(db)

        # Manually run matching steps since we don't have real PDF
        patient_match = await processor._match_patient(SAMPLE_OCR_TEXT_1, fax.id)

        if patient_match['matched']:
            provider_matches = await processor._match_provider_requests(
                patient_id=patient_match['patient_id'],
                sender_fax=fax.sender,
                fax_id=fax.id,
                ocr_text=SAMPLE_OCR_TEXT_1
            )

            completed = await processor._check_and_finalize_requests(
                patient_match['patient_id']
            )

            print(f"\nComplete Pipeline Results:")
            print(f"  Patient Matched: {patient_match['matched']}")
            print(f"  Provider Requests Matched: {len(provider_matches)}")
            print(f"  Requests Completed: {len(completed)}")

            if completed:
                # Check final status
                await db.refresh(record_request)
                print(f"  Final Status: {record_request.status}")
                print(f"  Compiled PDF: {record_request.compiled_pdf_path}")
                print(f"\n✅ Pipeline completed successfully!")
            else:
                print(f"\n⏳ Pipeline processed but request not yet complete")
        else:
            print(f"\n❌ Pipeline failed at patient matching")


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("INCOMING FAX PROCESSING TEST SUITE")
    print("=" * 80 + "\n")

    tests = [
        ("OCR Parsing", test_ocr_parsing),
        ("Patient Matching", test_patient_matching),
        ("Provider Matching", test_provider_matching),
        ("Full Pipeline", test_full_pipeline)
    ]

    for test_name, test_func in tests:
        try:
            print(f"\n▶ Running: {test_name}")
            await test_func()
            print(f"✅ {test_name} completed")
        except Exception as e:
            print(f"❌ {test_name} failed: {e}")
            logger.exception(f"Test failed: {test_name}")

        print("\n" + "-" * 80)
        await asyncio.sleep(1)  # Brief pause between tests

    print("\n" + "=" * 80)
    print("TEST SUITE COMPLETE")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())