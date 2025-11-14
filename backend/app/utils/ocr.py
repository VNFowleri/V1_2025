"""
Improved OCR and Patient Information Extraction for Medical Faxes

This module provides enhanced OCR text extraction and intelligent parsing
of patient information from medical records faxes with strict contextual matching.

Key improvements:
1. All pages are processed (already working correctly)
2. Strict contextual parsing - only matches patient info with proper markers
3. Enhanced DOB extraction with multiple format support
4. Detailed logging for debugging parsing issues
"""

import os
import re
import logging
from typing import Tuple, Optional, Dict, List
from datetime import datetime, date
import pytesseract
from pdf2image import convert_from_path

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text from ALL pages of PDF using OCR with enhanced preprocessing.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Extracted text as string from all pages concatenated
    """
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return ""

    try:
        logger.info(f"Starting OCR on: {pdf_path}")

        # Convert ALL pages of PDF to images at high DPI for better OCR
        images = convert_from_path(pdf_path, dpi=300)
        logger.info(f"Converted PDF to {len(images)} page(s)")

        all_text = []

        # Process EVERY page
        for page_num, img in enumerate(images, start=1):
            logger.debug(f"Processing page {page_num}/{len(images)}")

            # Convert to grayscale for better OCR
            img = img.convert("L")

            # Enhance contrast (binarization)
            # Pixels below 140 become black (0), above become white (255)
            img = img.point(lambda x: 0 if x < 140 else 255)

            # Run Tesseract OCR with page segmentation mode 6 (uniform block of text)
            text = pytesseract.image_to_string(img, config='--psm 6')
            all_text.append(text)

            logger.debug(f"Page {page_num} extracted {len(text)} characters")

        # Concatenate all pages with clear page breaks
        full_text = "\n\n=== PAGE BREAK ===\n\n".join(all_text)
        logger.info(f"OCR complete: extracted {len(full_text)} total characters from {len(images)} pages")

        # Log first 500 chars for debugging
        logger.debug(f"First 500 chars of OCR text:\n{full_text[:500]}")

        return full_text

    except Exception as e:
        logger.exception(f"Failed OCR on PDF: {pdf_path}. Error: {e}")
        return ""


def parse_name_and_dob(ocr_text: str) -> Tuple[Optional[str], Optional[str], Optional[date]]:
    """
    Parse patient name and date of birth from OCR text using STRICT contextual matching.

    This function looks for explicit markers like "Patient Name:", "Patient:", "DOB:", etc.
    to avoid false matches on names that appear in headers, signatures, or other contexts.

    Supports various formats:
    - Patient Name: John Doe
    - Patient: John Michael Doe
    - Name: Doe, John (Last, First format)
    - DOB: 01/15/1980
    - Date of Birth: 1980-01-15
    - DOB: Jan 15, 1980

    Args:
        ocr_text: Text extracted from fax via OCR (from all pages)

    Returns:
        Tuple of (first_name, last_name, date_of_birth)
        Returns (None, None, None) if parsing fails
    """
    if not ocr_text:
        logger.warning("Empty OCR text provided")
        return None, None, None

    # Parse name with strict contextual matching
    name_result = _parse_name_strict(ocr_text)
    first_name = name_result.get("first_name")
    last_name = name_result.get("last_name")

    # Parse DOB with contextual matching
    dob = _parse_dob_strict(ocr_text)

    logger.info(
        f"Parsed: first_name={first_name}, last_name={last_name}, dob={dob}"
    )

    return first_name, last_name, dob


def _parse_name_strict(text: str) -> Dict[str, Optional[str]]:
    """
    Parse patient name from text using STRICT contextual pattern matching.

    Only matches names that appear with explicit markers like:
    - "Patient Name:"
    - "Patient:"
    - "Name:" (when clearly in patient info section)

    Does NOT match random capitalized words without context.

    Returns dict with first_name and last_name keys.
    """
    # STRICT patterns - must have explicit context markers
    # Ordered by specificity (most specific first)
    name_patterns = [
        # Pattern 1: "Patient Name: First Last" (most explicit)
        (
            r'Patient\s+Name\s*[:\-–—]\s*([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?)\s+([A-Z][a-z]+)',
            False,  # Not reversed (First Last)
            "Patient Name: First Last"
        ),

        # Pattern 2: "Patient Name: Last, First" (explicit with comma)
        (
            r'Patient\s+Name\s*[:\-–—]\s*([A-Z][a-z]+),\s*([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?)',
            True,  # Reversed (Last, First)
            "Patient Name: Last, First"
        ),

        # Pattern 3: "Patient: First Last" (explicit patient marker)
        (
            r'Patient\s*[:\-–—]\s*([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?)\s+([A-Z][a-z]+)',
            False,
            "Patient: First Last"
        ),

        # Pattern 4: "Patient: Last, First" (explicit patient marker with comma)
        (
            r'Patient\s*[:\-–—]\s*([A-Z][a-z]+),\s*([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?)',
            True,
            "Patient: Last, First"
        ),

        # Pattern 5: "Name: First Last" (when near other patient info like DOB)
        # Only matches if "DOB" or "Date of Birth" appears within 200 chars
        (
            r'Name\s*[:\-–—]\s*([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?)\s+([A-Z][a-z]+)(?=.{0,200}(?:DOB|Date\s+of\s+Birth))',
            False,
            "Name: First Last (near DOB)"
        ),

        # Pattern 6: "Name: Last, First" (with comma, near DOB)
        (
            r'Name\s*[:\-–—]\s*([A-Z][a-z]+),\s*([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?)',
            True,
            "Name: Last, First"
        ),

        # Pattern 7: "PATIENT INFORMATION" section header followed by name
        (
            r'PATIENT\s+INFORMATION.*?Name\s*[:\-–—]?\s*([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?)\s+([A-Z][a-z]+)',
            False,
            "Patient Information section"
        ),

        # Pattern 8: Table-like format "Patient Name    First Last"
        (
            r'Patient\s+Name\s{2,}([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?)\s+([A-Z][a-z]+)',
            False,
            "Patient Name (table format)"
        ),
    ]

    for pattern, is_reversed, pattern_desc in name_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)

        if match:
            if is_reversed:
                # Last name is first capture group
                last_name = match.group(1).strip()
                first_name = match.group(2).strip()
            else:
                # First name is first capture group
                first_name = match.group(1).strip()
                last_name = match.group(2).strip()

            # Remove middle initial if present (e.g., "John M." -> "John")
            first_name = re.sub(r'\s+[A-Z]\.?\s*$', '', first_name)

            # Remove any trailing punctuation
            first_name = first_name.rstrip('.,;:')
            last_name = last_name.rstrip('.,;:')

            logger.info(
                f"✅ Name matched with pattern '{pattern_desc}': "
                f"{first_name} {last_name}"
            )

            return {
                "first_name": first_name,
                "last_name": last_name
            }

    logger.warning("❌ Could not parse patient name from text (no contextual markers found)")
    logger.debug(f"Searched in text snippet: {text[:500]}...")

    return {
        "first_name": None,
        "last_name": None
    }


def _parse_dob_strict(text: str) -> Optional[date]:
    """
    Parse date of birth from text using STRICT contextual patterns.

    Only matches dates that appear with explicit DOB markers:
    - "DOB:"
    - "Date of Birth:"
    - "Birth Date:"

    Does NOT match random dates without context.

    Supports multiple date formats:
    - MM/DD/YYYY
    - MM/DD/YY
    - YYYY-MM-DD
    - Month DD, YYYY (e.g., "Jan 15, 1980")
    - DD-MM-YYYY
    """
    # STRICT DOB patterns - must have explicit context markers
    dob_patterns = [
        # Pattern 1: "DOB: MM/DD/YYYY" or "DOB: MM/DD/YY"
        (
            r'DOB\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "DOB: MM/DD/YYYY"
        ),

        # Pattern 2: "Date of Birth: MM/DD/YYYY"
        (
            r'Date\s+of\s+Birth\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Date of Birth: MM/DD/YYYY"
        ),

        # Pattern 3: "Birth Date: MM/DD/YYYY"
        (
            r'Birth\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Birth Date: MM/DD/YYYY"
        ),

        # Pattern 4: "DOB: YYYY-MM-DD" (ISO format)
        (
            r'DOB\s*[:\-–—]\s*(\d{4}-\d{2}-\d{2})',
            ["%Y-%m-%d"],
            "DOB: YYYY-MM-DD"
        ),

        # Pattern 5: "DOB: Month DD, YYYY" (e.g., "Jan 15, 1980" or "January 15, 1980")
        (
            r'DOB\s*[:\-–—]\s*([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})',
            ["%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"],
            "DOB: Month DD, YYYY"
        ),

        # Pattern 6: "Date of Birth: Month DD, YYYY"
        (
            r'Date\s+of\s+Birth\s*[:\-–—]\s*([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})',
            ["%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"],
            "Date of Birth: Month DD, YYYY"
        ),

        # Pattern 7: Table format "DOB    MM/DD/YYYY"
        (
            r'DOB\s{2,}(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "DOB (table format)"
        ),
    ]

    for pattern, formats, pattern_desc in dob_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)

        if match:
            dob_str = match.group(1).strip()

            # Try each format
            for fmt in formats:
                try:
                    parsed_date = datetime.strptime(dob_str, fmt).date()

                    # Validate date is reasonable (not in future, not too old)
                    today = date.today()
                    age = (today - parsed_date).days / 365.25

                    if 0 <= age <= 120:  # Reasonable age range
                        logger.info(
                            f"✅ DOB matched with pattern '{pattern_desc}': "
                            f"{parsed_date} (age: {age:.1f} years)"
                        )
                        return parsed_date
                    else:
                        logger.debug(
                            f"Parsed date {parsed_date} results in age {age:.1f}, "
                            "which is outside reasonable range (0-120 years)"
                        )

                except ValueError:
                    continue

    logger.warning("❌ Could not parse DOB from text (no contextual markers found)")
    logger.debug(f"Searched in text snippet: {text[:500]}...")

    return None


def extract_hospital_names(ocr_text: str) -> List[str]:
    """
    Extract potential hospital/provider names from OCR text.

    Useful for matching incoming faxes to provider requests.

    Args:
        ocr_text: Text extracted from fax

    Returns:
        List of potential hospital names found
    """
    hospital_keywords = [
        r'Hospital',
        r'Medical Center',
        r'Clinic',
        r'Health System',
        r'Healthcare',
        r'Regional Medical',
        r'University Hospital',
        r'Community Hospital',
        r'Memorial',
        r'General Hospital',
        r'Children\'s Hospital',
        r'Veterans Affairs',
        r'VA Medical',
    ]

    hospitals = []

    # Look for hospital names (typically capitalized words before/after keyword)
    for keyword in hospital_keywords:
        pattern = rf'([A-Z][A-Za-z\s&]+{keyword}[A-Za-z\s&]*)'
        matches = re.findall(pattern, ocr_text)

        for match in matches:
            # Clean up the match
            cleaned = match.strip()
            # Remove excessive whitespace
            cleaned = re.sub(r'\s+', ' ', cleaned)

            if cleaned and len(cleaned) > 5:  # Skip very short matches
                hospitals.append(cleaned)

    # Remove duplicates while preserving order
    seen = set()
    unique_hospitals = []
    for h in hospitals:
        h_lower = h.lower()
        if h_lower not in seen:
            seen.add(h_lower)
            unique_hospitals.append(h)

    if unique_hospitals:
        logger.info(f"Extracted {len(unique_hospitals)} hospital name(s): {unique_hospitals}")
    else:
        logger.debug("No hospital names found in text")

    return unique_hospitals


def debug_print_ocr_snippet(ocr_text: str, max_length: int = 1000) -> None:
    """
    Helper function to print a snippet of OCR text for debugging.

    Useful when troubleshooting parsing issues.

    Args:
        ocr_text: The OCR extracted text
        max_length: Maximum length of snippet to print
    """
    if not ocr_text:
        logger.info("OCR text is empty")
        return

    snippet = ocr_text[:max_length]
    logger.info(f"OCR Text Snippet ({len(ocr_text)} total chars):\n{'=' * 60}\n{snippet}\n{'=' * 60}")