"""
Parsing Utilities for Medical Record Processing

Functions for extracting structured information from OCR text:
- Patient names and dates of birth
- Encounter/service dates
- Hospital names
- Phone number normalization
"""

import re
import logging
from datetime import date, datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)


def parse_name_and_dob(ocr_text: str) -> Dict[str, Optional[any]]:
    """
    Parse patient name and date of birth from OCR text using strict contextual matching.
    
    Returns dict with keys: first_name, last_name, dob
    """
    # Parse name
    name_result = _parse_patient_name(ocr_text)
    
    # Parse DOB
    dob = _parse_dob_strict(ocr_text)
    
    return {
        "first_name": name_result.get("first_name"),
        "last_name": name_result.get("last_name"),
        "dob": dob
    }


def _parse_patient_name(text: str) -> Dict[str, Optional[str]]:
    """
    Parse patient name from text using strict contextual patterns.
    
    Only matches names that appear with explicit markers like "Patient Name:", "Patient:", etc.
    """
    # Pattern 1: "Patient Name: First Last" or "Patient: First Last"
    patterns = [
        r'Patient\s+Name\s*[:\-–—]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]*\.?)?\s+[A-Z][a-z]+)',
        r'Patient\s*[:\-–—]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]*\.?)?\s+[A-Z][a-z]+)',
        r'Name\s*[:\-–—]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]*\.?)?\s+[A-Z][a-z]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            full_name = match.group(1).strip()
            parts = full_name.split()
            
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = parts[-1]
                
                logger.info(f"✅ Parsed patient name: {first_name} {last_name}")
                return {
                    "first_name": first_name,
                    "last_name": last_name
                }
    
    # Pattern 2: "Last, First" format
    pattern = r'Patient\s*[:\-–—]\s*([A-Z][a-z]+),\s*([A-Z][a-z]+)'
    match = re.search(pattern, text, flags=re.MULTILINE)
    if match:
        last_name = match.group(1).strip()
        first_name = match.group(2).strip()
        
        logger.info(f"✅ Parsed patient name (Last, First format): {first_name} {last_name}")
        return {
            "first_name": first_name,
            "last_name": last_name
        }
    
    logger.warning("❌ Could not parse patient name from text")
    return {
        "first_name": None,
        "last_name": None
    }


def _parse_dob_strict(text: str) -> Optional[date]:
    """
    Parse date of birth from text using STRICT contextual patterns.
    
    Only matches dates that appear with explicit DOB markers.
    """
    dob_patterns = [
        # Pattern 1: "DOB: MM/DD/YYYY"
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
        # Pattern 4: "DOB: YYYY-MM-DD"
        (
            r'DOB\s*[:\-–—]\s*(\d{4}-\d{2}-\d{2})',
            ["%Y-%m-%d"],
            "DOB: YYYY-MM-DD"
        ),
        # Pattern 5: "DOB: Month DD, YYYY"
        (
            r'DOB\s*[:\-–—]\s*([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})',
            ["%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"],
            "DOB: Month DD, YYYY"
        ),
    ]
    
    for pattern, formats, pattern_desc in dob_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        
        if match:
            dob_str = match.group(1).strip()
            
            for fmt in formats:
                try:
                    parsed_date = datetime.strptime(dob_str, fmt).date()
                    
                    # Validate reasonable age (0-120 years)
                    today = date.today()
                    age = (today - parsed_date).days / 365.25
                    
                    if 0 <= age <= 120:
                        logger.info(f"✅ DOB matched: {parsed_date} (age: {age:.1f} years)")
                        return parsed_date
                except ValueError:
                    continue
    
    logger.warning("❌ Could not parse DOB from text")
    return None


def parse_encounter_date(ocr_text: str) -> Optional[date]:
    """
    Parse encounter/service date from OCR text.
    
    Looks for patterns like:
    - "Date of Service: MM/DD/YYYY"
    - "Visit Date: MM/DD/YYYY"
    - "Encounter Date: MM/DD/YYYY"
    - "Service Date: MM/DD/YYYY"
    - "Admission Date: MM/DD/YYYY"
    - "Discharge Date: MM/DD/YYYY"
    """
    encounter_patterns = [
        (r'Date\s+of\s+Service\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', "Date of Service"),
        (r'Service\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', "Service Date"),
        (r'Visit\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', "Visit Date"),
        (r'Encounter\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', "Encounter Date"),
        (r'Admission\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', "Admission Date"),
        (r'Discharge\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', "Discharge Date"),
    ]
    
    date_formats = ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"]
    
    for pattern, pattern_name in encounter_patterns:
        match = re.search(pattern, ocr_text, flags=re.IGNORECASE | re.MULTILINE)
        
        if match:
            date_str = match.group(1).strip()
            
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt).date()
                    
                    # Validate date is in the past and within ~50 years
                    today = date.today()
                    if parsed_date <= today and (today - parsed_date).days <= 365 * 50:
                        logger.info(f"✅ Encounter date matched ({pattern_name}): {parsed_date}")
                        return parsed_date
                except ValueError:
                    continue
    
    logger.debug("No encounter date found in text")
    return None


def extract_hospital_names(ocr_text: str) -> List[str]:
    """
    Extract potential hospital/provider names from OCR text.
    
    Useful for matching incoming faxes to provider requests.
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
    
    for keyword in hospital_keywords:
        pattern = rf'([A-Z][A-Za-z\s&]+{keyword}[A-Za-z\s&]*)'
        matches = re.findall(pattern, ocr_text)
        
        for match in matches:
            cleaned = match.strip()
            cleaned = re.sub(r'\s+', ' ', cleaned)
            
            if cleaned and len(cleaned) > 5:
                hospitals.append(cleaned)
    
    # Remove duplicates
    seen = set()
    unique_hospitals = []
    for h in hospitals:
        h_lower = h.lower()
        if h_lower not in seen:
            seen.add(h_lower)
            unique_hospitals.append(h)
    
    if unique_hospitals:
        logger.info(f"Extracted {len(unique_hospitals)} hospital name(s): {unique_hospitals}")
    
    return unique_hospitals


def normalize_phone_number(phone: str) -> Optional[str]:
    """
    Normalize phone number to last 10 digits.
    
    Examples:
    - "+1 (555) 123-4567" -> "5551234567"
    - "555-123-4567" -> "5551234567"
    - "15551234567" -> "5551234567"
    """
    if not phone:
        return None
    
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone)
    
    # Get last 10 digits
    if len(digits) >= 10:
        return digits[-10:]
    
    return None


def format_fax_number(fax: str) -> str:
    """
    Format fax number in E.164 format (+1XXXXXXXXXX).
    
    Examples:
    - "5551234567" -> "+15551234567"
    - "+1-555-123-4567" -> "+15551234567"
    """
    if not fax:
        return ""
    
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', fax)
    
    # Ensure it has country code
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    else:
        return f"+{digits}"


def debug_print_ocr_snippet(ocr_text: str, max_length: int = 1000) -> None:
    """
    Helper function to print a snippet of OCR text for debugging.
    """
    if not ocr_text:
        logger.info("OCR text is empty")
        return
    
    snippet = ocr_text[:max_length]
    logger.info(f"OCR Text Snippet ({len(ocr_text)} total chars):\n{'=' * 60}\n{snippet}\n{'=' * 60}")
