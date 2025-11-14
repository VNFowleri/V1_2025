"""
Incoming Fax Processor

Handles the complete processing pipeline for incoming faxes:
1. Parse patient information (name, DOB)
2. Match to patient records
3. Parse encounter date
4. Match to provider requests
5. Update request status
"""

import logging
from typing import Optional, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.fax_file import FaxFile
from app.models.patient import Patient
from app.models.provider import Provider
from app.models.record_request import RecordRequest, ProviderRequest
from app.utils.parsing import (
    parse_name_and_dob,
    parse_encounter_date,
    extract_hospital_names,
    normalize_phone_number
)
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


class IncomingFaxProcessor:
    """
    Processes incoming faxes and links them to patients and requests.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def process_incoming_fax(
            self,
            job_id: str,
            fax_file: FaxFile
    ) -> bool:
        """
        Process an incoming fax through the complete pipeline.

        Args:
            job_id: Fax job ID
            fax_file: FaxFile database record

        Returns:
            True if processing succeeded, False otherwise
        """
        logger.info(f"🔍 Processing fax {job_id} (FaxFile #{fax_file.id})")

        # Validate OCR text exists
        if not fax_file.ocr_text or len(fax_file.ocr_text.strip()) == 0:
            logger.error(f"❌ No OCR text available for fax {job_id}")
            return False

        if fax_file.ocr_text.startswith("[OCR"):
            logger.error(f"❌ OCR failed for fax {job_id}: {fax_file.ocr_text}")
            return False

        try:
            # Step 1: Parse patient info
            logger.info("Step 1: Parsing patient information...")
            patient_match = await self._match_patient(fax_file)

            if not patient_match:
                logger.warning(f"⚠️ Could not match fax {job_id} to any patient")
                return False

            patient_id, confidence = patient_match
            logger.info(f"✅ Matched to Patient #{patient_id} (confidence: {confidence:.2f})")

            # Update fax record with patient
            fax_file.patient_id = patient_id
            await self.db.commit()

            # Step 2: Parse encounter date
            logger.info("Step 2: Parsing encounter date...")
            encounter_date = parse_encounter_date(fax_file.ocr_text)

            if encounter_date:
                logger.info(f"✅ Found encounter date: {encounter_date}")
                fax_file.encounter_date = encounter_date
                await self.db.commit()
            else:
                logger.info("ℹ️ No encounter date found (using received time for sorting)")

            # Step 3: Match to provider requests
            logger.info("Step 3: Matching to provider requests...")
            matched_requests = await self._match_provider_requests(fax_file)

            if matched_requests:
                logger.info(f"✅ Matched to {len(matched_requests)} provider request(s)")

                # Check if any record requests are now complete
                await self._check_request_completion(patient_id)
            else:
                logger.info("ℹ️ No provider requests matched (fax may be unsolicited)")

            logger.info(f"✅ Successfully processed fax {job_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error processing fax {job_id}: {str(e)}", exc_info=True)
            return False

    async def _match_patient(
            self,
            fax_file: FaxFile
    ) -> Optional[Tuple[int, float]]:
        """
        Match fax to a patient based on name and DOB.

        Returns:
            Tuple of (patient_id, confidence) or None if no match
        """
        # Parse name and DOB from OCR text
        parsed = parse_name_and_dob(fax_file.ocr_text)

        first_name = parsed.get("first_name")
        last_name = parsed.get("last_name")
        dob = parsed.get("dob")

        if not dob:
            logger.warning("❌ Could not parse DOB from fax - cannot match patient")
            return None

        logger.info(f"Parsed info - Name: {first_name} {last_name}, DOB: {dob}")

        # Find all patients with matching DOB
        result = await self.db.execute(
            select(Patient).where(Patient.date_of_birth == dob)
        )
        candidates = result.scalars().all()

        if not candidates:
            logger.warning(f"No patients found with DOB {dob}")
            return None

        logger.info(f"Found {len(candidates)} patient(s) with DOB {dob}")

        # If no name parsed, but only one patient with this DOB
        if (not first_name or not last_name) and len(candidates) == 1:
            logger.info(f"Only one patient with DOB {dob}, using that match")
            return (candidates[0].id, 0.9)

        if not first_name or not last_name:
            logger.warning("Could not parse patient name and multiple DOB matches exist")
            return None

        # Fuzzy match names
        parsed_full_name = f"{first_name} {last_name}".lower()
        best_match = None
        best_score = 0

        for patient in candidates:
            patient_full_name = f"{patient.first_name} {patient.last_name}".lower()

            # Use multiple matching strategies
            ratio_score = fuzz.ratio(parsed_full_name, patient_full_name)
            token_sort_score = fuzz.token_sort_ratio(parsed_full_name, patient_full_name)
            partial_score = fuzz.partial_ratio(parsed_full_name, patient_full_name)

            # Take the best score
            score = max(ratio_score, token_sort_score, partial_score)

            logger.debug(
                f"Patient #{patient.id} ({patient_full_name}): "
                f"ratio={ratio_score}, token_sort={token_sort_score}, "
                f"partial={partial_score} → best={score}"
            )

            if score > best_score:
                best_score = score
                best_match = patient

        # Require minimum score of 80
        if best_match and best_score >= 80:
            confidence = best_score / 100.0
            logger.info(
                f"Best match: Patient #{best_match.id} "
                f"({best_match.first_name} {best_match.last_name}) "
                f"with score {best_score}"
            )
            return (best_match.id, confidence)

        logger.warning(
            f"Best match score {best_score} below threshold (80). "
            "No confident patient match."
        )
        return None

    async def _match_provider_requests(
            self,
            fax_file: FaxFile
    ) -> list:
        """
        Match fax to provider requests.

        Tries two strategies:
        1. Match by fax number
        2. Match by hospital name (content-based)

        Returns:
            List of matched ProviderRequest IDs
        """
        if not fax_file.patient_id:
            logger.warning("Cannot match provider requests - no patient linked")
            return []

        matched_requests = []

        # Strategy 1: Match by fax number
        if fax_file.sender:
            logger.info(f"Trying fax number match: {fax_file.sender}")
            matches = await self._match_by_fax_number(fax_file)
            matched_requests.extend(matches)

        # Strategy 2: Match by hospital name (if no fax match)
        if not matched_requests:
            logger.info("Trying hospital name match...")
            matches = await self._match_by_hospital_name(fax_file)
            matched_requests.extend(matches)

        return matched_requests

    async def _match_by_fax_number(
            self,
            fax_file: FaxFile
    ) -> list:
        """
        Match fax to provider requests by comparing fax numbers.
        """
        sender_normalized = normalize_phone_number(fax_file.sender)

        if not sender_normalized:
            logger.debug("Could not normalize sender fax number")
            return []

        logger.debug(f"Normalized sender fax: {sender_normalized}")

        # Get all record requests for this patient
        result = await self.db.execute(
            select(RecordRequest).where(
                and_(
                    RecordRequest.patient_id == fax_file.patient_id,
                    RecordRequest.status.in_(['pending', 'in_progress'])
                )
            )
        )
        record_requests = result.scalars().all()

        matched_provider_requests = []

        for record_request in record_requests:
            # Get provider requests for this record request
            result = await self.db.execute(
                select(ProviderRequest).where(
                    and_(
                        ProviderRequest.record_request_id == record_request.id,
                        ProviderRequest.status.in_(['fax_sent', 'fax_delivered'])
                    )
                )
            )
            provider_requests = result.scalars().all()

            for pr in provider_requests:
                # Get the provider
                if pr.provider_id:
                    result = await self.db.execute(
                        select(Provider).where(Provider.id == pr.provider_id)
                    )
                    provider = result.scalar_one_or_none()

                    if provider and provider.fax:
                        provider_fax_normalized = normalize_phone_number(provider.fax)

                        if provider_fax_normalized == sender_normalized:
                            logger.info(
                                f"✅ Fax number match! ProviderRequest #{pr.id} "
                                f"({provider.name})"
                            )

                            # Update provider request
                            pr.status = "response_received"
                            pr.inbound_fax_id = fax_file.id
                            pr.responded_at = datetime.utcnow()

                            matched_provider_requests.append(pr.id)

        if matched_provider_requests:
            await self.db.commit()

        return matched_provider_requests

    async def _match_by_hospital_name(
            self,
            fax_file: FaxFile
    ) -> list:
        """
        Match fax to provider requests by extracting and matching hospital names.
        """
        # Extract hospital names from OCR text
        hospital_names = extract_hospital_names(fax_file.ocr_text)

        if not hospital_names:
            logger.debug("No hospital names extracted from fax")
            return []

        logger.info(f"Extracted hospital names: {hospital_names}")

        # Get all record requests for this patient
        result = await self.db.execute(
            select(RecordRequest).where(
                and_(
                    RecordRequest.patient_id == fax_file.patient_id,
                    RecordRequest.status.in_(['pending', 'in_progress'])
                )
            )
        )
        record_requests = result.scalars().all()

        matched_provider_requests = []

        for record_request in record_requests:
            # Get provider requests
            result = await self.db.execute(
                select(ProviderRequest).where(
                    and_(
                        ProviderRequest.record_request_id == record_request.id,
                        ProviderRequest.status.in_(['fax_sent', 'fax_delivered'])
                    )
                )
            )
            provider_requests = result.scalars().all()

            for pr in provider_requests:
                if pr.provider_id:
                    result = await self.db.execute(
                        select(Provider).where(Provider.id == pr.provider_id)
                    )
                    provider = result.scalar_one_or_none()

                    if provider:
                        # Fuzzy match provider name against extracted hospital names
                        provider_name_lower = provider.name.lower()

                        for hospital_name in hospital_names:
                            hospital_name_lower = hospital_name.lower()

                            score = fuzz.token_sort_ratio(
                                provider_name_lower,
                                hospital_name_lower
                            )

                            if score >= 70:
                                logger.info(
                                    f"✅ Hospital name match! ProviderRequest #{pr.id} "
                                    f"({provider.name}) matched '{hospital_name}' "
                                    f"(score: {score})"
                                )

                                # Update provider request
                                pr.status = "response_received"
                                pr.inbound_fax_id = fax_file.id
                                pr.responded_at = datetime.utcnow()

                                matched_provider_requests.append(pr.id)
                                break  # Don't match same provider multiple times

        if matched_provider_requests:
            await self.db.commit()

        return matched_provider_requests

    async def _check_request_completion(self, patient_id: int):
        """
        Check if any record requests for this patient are now complete.

        A request is complete when all provider requests have either:
        - response_received
        - fax_failed
        """
        result = await self.db.execute(
            select(RecordRequest).where(
                and_(
                    RecordRequest.patient_id == patient_id,
                    RecordRequest.status.in_(['pending', 'in_progress'])
                )
            )
        )
        record_requests = result.scalars().all()

        for rr in record_requests:
            # Get all provider requests
            result = await self.db.execute(
                select(ProviderRequest).where(
                    ProviderRequest.record_request_id == rr.id
                )
            )
            provider_requests = result.scalars().all()

            if not provider_requests:
                continue

            # Check if all are in terminal state
            terminal_states = ['response_received', 'fax_failed']
            all_complete = all(
                pr.status in terminal_states
                for pr in provider_requests
            )

            if all_complete:
                logger.info(
                    f"✅ RecordRequest #{rr.id} is now complete "
                    f"(all providers responded or failed)"
                )

                # We could compile PDFs here, but for now just mark complete
                # The compilation happens on-demand in the portal
                rr.status = "complete"
                rr.completed_at = datetime.utcnow()

        await self.db.commit()