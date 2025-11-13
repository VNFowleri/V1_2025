# app/services/fax_processor.py - v2.1
"""
Enhanced Incoming Fax Processing Service with Encounter Date Parsing

This service handles the complete workflow of processing incoming medical records faxes:
1. Download fax PDF from iFax
2. OCR extraction to create searchable text
3. Parse patient name and DOB from fax content
4. Parse encounter date (NEW in v2.1)
5. Fuzzy match patient with existing database records
6. Match fax to outgoing provider requests by fax number and hospital name
7. Aggregate and compile all records when requests are complete
8. Generate final searchable PDF package for patient portal

Key Features:
- Fuzzy matching algorithms for patient identification
- Multi-factor provider matching (fax number + hospital name)
- Encounter date extraction for chronological ordering
- Confidence scoring for all matches
- Comprehensive error handling and logging
- Automatic retry mechanisms
- Status tracking throughout the process
"""

import os
import re
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, or_
from rapidfuzz import fuzz, process

from app.models import FaxFile, Patient, Provider, RecordRequest, ProviderRequest
from app.utils.ocr import extract_text_from_pdf, parse_name_and_dob, extract_hospital_names
from app.utils.encounter_date_parser import parse_encounter_date  # NEW
from app.services.ifax_service import download_fax
from app.services.pdf_ops import ocr_to_searchable_pdf, merge_pdfs

logger = logging.getLogger(__name__)

# Configuration constants
PATIENT_NAME_MATCH_THRESHOLD = 80  # Fuzzy match score threshold (0-100)
HOSPITAL_NAME_MATCH_THRESHOLD = 70  # For matching provider names
MIN_CONFIDENCE_FOR_AUTO_LINK = 0.85  # Minimum confidence to auto-link without review


class FaxProcessingError(Exception):
    """Custom exception for fax processing errors."""
    pass


class IncomingFaxProcessor:
    """
    Handles the complete processing pipeline for incoming medical records faxes.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def process_incoming_fax(
            self,
            job_id: str,
            fax_record_id: int,
            transaction_id: int,
            direction: Optional[str] = None
    ) -> Dict:
        """
        Main entry point for processing an incoming fax.

        Returns:
            Dict with processing results including:
            - success: bool
            - fax_id: int
            - patient_matched: bool
            - patient_id: Optional[int]
            - provider_matched: bool
            - provider_request_ids: List[int]
            - request_completed: bool
            - completed_request_ids: List[int]
            - encounter_date_found: bool (NEW)
            - errors: List[str]
        """
        self.logger.info(f"🔄 Starting fax processing: JobID={job_id}, FaxID={fax_record_id}")

        result = {
            "success": False,
            "fax_id": fax_record_id,
            "patient_matched": False,
            "patient_id": None,
            "provider_matched": False,
            "provider_request_ids": [],
            "request_completed": False,
            "completed_request_ids": [],
            "encounter_date_found": False,  # NEW
            "errors": []
        }

        try:
            # Step 1: Download the fax PDF
            self.logger.info(f"📥 Step 1/7: Downloading fax PDF...")
            download_result = await self._download_fax_file(job_id, transaction_id)

            if not download_result["success"]:
                result["errors"].append(f"Download failed: {download_result.get('error')}")
                return result

            file_path = download_result["file_path"]
            self.logger.info(f"✅ Downloaded to: {file_path}")

            # Step 2: OCR the PDF
            self.logger.info(f"📄 Step 2/7: Extracting text via OCR...")
            ocr_text = await self._extract_text(file_path)

            if not ocr_text:
                result["errors"].append("OCR extraction failed or returned empty text")
                self.logger.warning("⚠️ OCR returned no text")
            else:
                self.logger.info(f"✅ Extracted {len(ocr_text)} characters of text")

            # Step 3: Update FaxFile record with PDF data and OCR text
            self.logger.info(f"💾 Step 3/7: Updating fax record in database...")
            await self._update_fax_record(fax_record_id, file_path, ocr_text)
            self.logger.info(f"✅ Fax record updated")

            # Step 4: Parse encounter date (NEW)
            self.logger.info(f"📅 Step 4/7: Parsing encounter date...")
            encounter_date = await self._parse_and_save_encounter_date(fax_record_id, ocr_text)

            if encounter_date:
                result["encounter_date_found"] = True
                self.logger.info(f"✅ Encounter date found: {encounter_date}")
            else:
                self.logger.warning("⚠️ No encounter date found in record")

            # Step 5: Parse and match patient
            self.logger.info(f"🔍 Step 5/7: Parsing patient information...")
            patient_match = await self._match_patient(ocr_text, fax_record_id)

            if patient_match["matched"]:
                result["patient_matched"] = True
                result["patient_id"] = patient_match["patient_id"]
                self.logger.info(
                    f"✅ Patient matched: ID={patient_match['patient_id']}, "
                    f"Name={patient_match['name']}, "
                    f"Confidence={patient_match['confidence']:.2%}"
                )
            else:
                result["errors"].append("Could not match patient from fax content")
                self.logger.warning(f"⚠️ No patient match found")
                return result

            # Step 6: Match to provider request
            self.logger.info(f"🏥 Step 6/7: Matching to provider requests...")
            fax_file = await self.db.get(FaxFile, fax_record_id)

            if fax_file and fax_file.sender:
                provider_matches = await self._match_provider_requests(
                    patient_id=patient_match["patient_id"],
                    sender_fax=fax_file.sender,
                    fax_id=fax_record_id,
                    ocr_text=ocr_text
                )

                if provider_matches:
                    result["provider_matched"] = True
                    result["provider_request_ids"] = provider_matches
                    self.logger.info(
                        f"✅ Matched to {len(provider_matches)} provider request(s): "
                        f"{provider_matches}"
                    )
                else:
                    self.logger.warning(
                        f"⚠️ No provider request match found for sender: {fax_file.sender}"
                    )

            # Step 7: Check if we can finalize any requests
            self.logger.info(f"📦 Step 7/7: Checking for request completion...")
            completed = await self._check_and_finalize_requests(patient_match["patient_id"])

            if completed:
                result["request_completed"] = True
                result["completed_request_ids"] = completed
                self.logger.info(
                    f"✅ Completed and compiled {len(completed)} request(s): {completed}"
                )

            result["success"] = True
            self.logger.info(f"✅ Fax processing complete: {result}")

        except Exception as e:
            self.logger.exception(f"❌ Fax processing failed: {e}")
            result["errors"].append(f"Processing exception: {str(e)}")

        return result

    async def _download_fax_file(self, job_id: str, transaction_id: int) -> Dict:
        """Download fax file from iFax API."""
        try:
            # Run synchronous download in thread pool
            download_result = await asyncio.to_thread(download_fax, job_id, transaction_id)

            file_path = download_result.get("file_path")

            if not file_path or not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": "Downloaded file not found or invalid path"
                }

            return {
                "success": True,
                "file_path": file_path
            }

        except Exception as e:
            self.logger.exception(f"Download failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _extract_text(self, file_path: str) -> str:
        """Extract text from PDF using OCR."""
        try:
            # Run synchronous OCR in thread pool
            ocr_text = await asyncio.to_thread(extract_text_from_pdf, file_path)
            return ocr_text or ""
        except Exception as e:
            self.logger.exception(f"OCR extraction failed: {e}")
            return ""

    async def _update_fax_record(
            self,
            fax_record_id: int,
            file_path: str,
            ocr_text: str
    ) -> None:
        """Update FaxFile record with PDF data and OCR text."""
        try:
            # Read PDF binary data
            with open(file_path, "rb") as f:
                pdf_content = f.read()

            # Update fax record
            fax = await self.db.get(FaxFile, fax_record_id)
            if fax:
                fax.file_path = os.path.abspath(file_path)
                fax.pdf_data = pdf_content
                fax.ocr_text = ocr_text
                self.db.add(fax)
                await self.db.commit()
                await self.db.refresh(fax)

        except Exception as e:
            self.logger.exception(f"Failed to update fax record: {e}")
            raise FaxProcessingError(f"Database update failed: {e}")

    async def _parse_and_save_encounter_date(
            self,
            fax_record_id: int,
            ocr_text: str
    ) -> Optional[str]:
        """
        Parse encounter date from OCR text and save to database.

        NEW in v2.1: Extracts date of service/visit from medical record.
        """
        try:
            # Parse encounter date
            encounter_date = parse_encounter_date(ocr_text)

            if encounter_date:
                # Save to database
                fax = await self.db.get(FaxFile, fax_record_id)
                if fax:
                    fax.encounter_date = encounter_date
                    self.db.add(fax)
                    await self.db.commit()
                    await self.db.refresh(fax)

                    self.logger.info(
                        f"💾 Saved encounter date: {encounter_date} "
                        f"({(datetime.now().date() - encounter_date).days // 365} years ago)"
                    )
                    return encounter_date

            return None

        except Exception as e:
            self.logger.exception(f"Failed to parse/save encounter date: {e}")
            return None

    async def _match_patient(
            self,
            ocr_text: str,
            fax_record_id: int
    ) -> Dict:
        """
        Match patient using fuzzy matching on name and exact DOB match.

        Returns:
            Dict with:
            - matched: bool
            - patient_id: Optional[int]
            - name: Optional[str]
            - confidence: float (0.0-1.0)
            - match_method: str
        """
        # Parse name and DOB from OCR text
        first_name, last_name, dob = parse_name_and_dob(ocr_text)

        if not (first_name and last_name and dob):
            self.logger.warning(
                f"Incomplete patient info parsed: "
                f"first={first_name}, last={last_name}, dob={dob}"
            )
            return {
                "matched": False,
                "patient_id": None,
                "name": None,
                "confidence": 0.0,
                "match_method": "parse_failed"
            }

        # Fetch all patients with matching DOB
        result = await self.db.execute(
            select(Patient).where(Patient.date_of_birth == dob)
        )
        candidates = result.scalars().all()

        if not candidates:
            self.logger.warning(f"No patients found with DOB: {dob}")
            return {
                "matched": False,
                "patient_id": None,
                "name": f"{first_name} {last_name}",
                "confidence": 0.0,
                "match_method": "no_dob_match"
            }

        # Use fuzzy matching to find best name match
        parsed_full_name = f"{first_name} {last_name}".lower()

        best_match = None
        best_score = 0

        for patient in candidates:
            patient_full_name = f"{patient.first_name} {patient.last_name}".lower()

            # Calculate fuzzy match score
            score = fuzz.ratio(parsed_full_name, patient_full_name)

            self.logger.debug(
                f"Comparing '{parsed_full_name}' with '{patient_full_name}': "
                f"score={score}"
            )

            if score > best_score:
                best_score = score
                best_match = patient

        # Check if best match exceeds threshold
        if best_match and best_score >= PATIENT_NAME_MATCH_THRESHOLD:
            # Update fax record with matched patient
            fax = await self.db.get(FaxFile, fax_record_id)
            if fax:
                fax.patient_id = best_match.id
                self.db.add(fax)
                await self.db.commit()

            confidence = best_score / 100.0  # Convert to 0-1 scale

            return {
                "matched": True,
                "patient_id": best_match.id,
                "name": f"{best_match.first_name} {best_match.last_name}",
                "confidence": confidence,
                "match_method": "fuzzy_name_exact_dob",
                "fuzzy_score": best_score
            }
        else:
            self.logger.warning(
                f"Best match score {best_score} below threshold "
                f"{PATIENT_NAME_MATCH_THRESHOLD}"
            )
            return {
                "matched": False,
                "patient_id": None,
                "name": f"{first_name} {last_name}",
                "confidence": best_score / 100.0 if best_match else 0.0,
                "match_method": "below_threshold",
                "best_score": best_score
            }

    async def _match_provider_requests(
            self,
            patient_id: int,
            sender_fax: str,
            fax_id: int,
            ocr_text: str
    ) -> List[int]:
        """
        Match incoming fax to provider requests using multiple strategies:
        1. Exact fax number match
        2. Fuzzy hospital name match from OCR text

        Returns list of ProviderRequest IDs that were matched and updated.
        """
        matched_request_ids = []

        # Normalize sender fax (remove formatting)
        sender_normalized = re.sub(r'\D', '', sender_fax)[-10:]  # Last 10 digits

        # Get all record requests for this patient
        rr_result = await self.db.execute(
            select(RecordRequest).where(RecordRequest.patient_id == patient_id)
        )
        record_requests = rr_result.scalars().all()

        for record_request in record_requests:
            # Get all provider requests for this record request
            pr_result = await self.db.execute(
                select(ProviderRequest).where(
                    ProviderRequest.record_request_id == record_request.id
                )
            )
            provider_requests = pr_result.scalars().all()

            for pr in provider_requests:
                # Skip if already matched
                if pr.status == "response_received":
                    continue

                # Strategy 1: Match by fax number
                if pr.provider_id:
                    provider = await self.db.get(Provider, pr.provider_id)

                    if provider and provider.fax:
                        provider_fax_normalized = re.sub(r'\D', '', provider.fax)[-10:]

                        if provider_fax_normalized == sender_normalized:
                            self.logger.info(
                                f"✅ Fax number match: ProviderRequest {pr.id}, "
                                f"Provider {provider.name}"
                            )

                            # Update provider request
                            pr.status = "response_received"
                            pr.inbound_fax_id = fax_id
                            pr.responded_at = datetime.utcnow()
                            self.db.add(pr)
                            await self.db.commit()

                            if pr.id not in matched_request_ids:
                                matched_request_ids.append(pr.id)

        # Strategy 2: Fuzzy match by hospital name in OCR text
        if ocr_text:
            hospital_names = extract_hospital_names(ocr_text)

            for record_request in record_requests:
                pr_result = await self.db.execute(
                    select(ProviderRequest).where(
                        ProviderRequest.record_request_id == record_request.id
                    )
                )
                provider_requests = pr_result.scalars().all()

                for pr in provider_requests:
                    if pr.status == "response_received" or pr.id in matched_request_ids:
                        continue

                    if pr.provider_id:
                        provider = await self.db.get(Provider, pr.provider_id)

                        if provider and provider.name:
                            # Try fuzzy matching against extracted hospital names
                            for hospital_name in hospital_names:
                                score = fuzz.ratio(
                                    provider.name.lower(),
                                    hospital_name.lower()
                                )

                                if score >= HOSPITAL_NAME_MATCH_THRESHOLD:
                                    self.logger.info(
                                        f"✅ Hospital name match: ProviderRequest {pr.id}, "
                                        f"Provider '{provider.name}' ~ '{hospital_name}' "
                                        f"(score: {score})"
                                    )

                                    # Update provider request
                                    pr.status = "response_received"
                                    pr.inbound_fax_id = fax_id
                                    pr.responded_at = datetime.utcnow()
                                    self.db.add(pr)
                                    await self.db.commit()

                                    if pr.id not in matched_request_ids:
                                        matched_request_ids.append(pr.id)
                                    break

        return matched_request_ids

    async def _check_and_finalize_requests(self, patient_id: int) -> List[int]:
        """
        Check if any record requests are complete (all providers responded).
        If so, aggregate all faxes into a single searchable PDF.

        Returns list of RecordRequest IDs that were completed.
        """
        completed_request_ids = []

        # Get all record requests for this patient
        result = await self.db.execute(
            select(RecordRequest).where(
                and_(
                    RecordRequest.patient_id == patient_id,
                    RecordRequest.status.in_(["pending", "in_progress"])
                )
            )
        )
        record_requests = result.scalars().all()

        for rr in record_requests:
            # Get all provider requests for this record request
            pr_result = await self.db.execute(
                select(ProviderRequest).where(
                    ProviderRequest.record_request_id == rr.id
                )
            )
            provider_requests = pr_result.scalars().all()

            if not provider_requests:
                continue

            # Check if all have received responses or failed
            all_complete = all(
                pr.status in ["response_received", "fax_failed"]
                for pr in provider_requests
            )

            if all_complete:
                # All responses received - time to aggregate!
                self.logger.info(
                    f"🎉 All providers responded for RecordRequest {rr.id}. "
                    f"Beginning aggregation..."
                )

                try:
                    compiled_path = await self._aggregate_faxes(patient_id, rr.id)

                    if compiled_path:
                        # Update record request
                        rr.status = "complete"
                        rr.compiled_pdf_path = compiled_path
                        rr.completed_at = datetime.utcnow()
                        self.db.add(rr)
                        await self.db.commit()

                        completed_request_ids.append(rr.id)
                        self.logger.info(f"✅ RecordRequest {rr.id} marked as complete")
                    else:
                        self.logger.error(f"Failed to aggregate faxes for request {rr.id}")

                except Exception as e:
                    self.logger.exception(f"Error finalizing request {rr.id}: {e}")

        return completed_request_ids

    async def _aggregate_faxes(
            self,
            patient_id: int,
            record_request_id: int
    ) -> Optional[str]:
        """
        Aggregate all faxes for a patient into a single searchable PDF.

        Returns path to compiled PDF, or None if failed.
        """
        import tempfile

        # Get all fax files for this patient
        result = await self.db.execute(
            select(FaxFile).where(FaxFile.patient_id == patient_id)
        )
        fax_files = result.scalars().all()

        if not fax_files:
            self.logger.warning(f"No fax files found for patient {patient_id}")
            return None

        self.logger.info(
            f"Aggregating {len(fax_files)} fax file(s) for patient {patient_id}"
        )

        # Create temporary directory for processing
        tmpdir = tempfile.mkdtemp()
        searchable_pdfs = []

        for fax in fax_files:
            if not fax.file_path or not os.path.exists(fax.file_path):
                self.logger.warning(f"Fax {fax.id} missing file, skipping")
                continue

            # Convert to searchable PDF
            searchable_path = os.path.join(tmpdir, f"searchable_{fax.id}.pdf")

            try:
                await asyncio.to_thread(
                    ocr_to_searchable_pdf,
                    fax.file_path,
                    searchable_path
                )
                searchable_pdfs.append(searchable_path)
                self.logger.debug(f"Created searchable PDF: {searchable_path}")
            except Exception as e:
                self.logger.warning(
                    f"Failed to create searchable PDF for fax {fax.id}: {e}, "
                    "using original"
                )
                searchable_pdfs.append(fax.file_path)

        if not searchable_pdfs:
            self.logger.error("No PDFs available to merge")
            return None

        # Merge all PDFs
        os.makedirs("storage", exist_ok=True)
        final_path = os.path.join(
            "storage",
            f"patient_{patient_id}_request_{record_request_id}_records.pdf"
        )

        try:
            await asyncio.to_thread(merge_pdfs, searchable_pdfs, final_path)
            self.logger.info(f"✅ Merged {len(searchable_pdfs)} PDFs into: {final_path}")
            return os.path.abspath(final_path)
        except Exception as e:
            self.logger.exception(f"Failed to merge PDFs: {e}")
            return None


# Convenience function for webhook handler
async def process_incoming_fax(
        job_id: str,
        fax_record_id: int,
        transaction_id: int,
        db: AsyncSession,
        direction: Optional[str] = None
) -> Dict:
    """
    Process an incoming fax through the complete pipeline.

    This is the main entry point called from the webhook handler.
    """
    processor = IncomingFaxProcessor(db)
    return await processor.process_incoming_fax(
        job_id=job_id,
        fax_record_id=fax_record_id,
        transaction_id=transaction_id,
        direction=direction
    )