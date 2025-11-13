"""
Enhanced OCR Utilities with Encounter Date Parsing

This module extends the OCR functionality to parse clinical encounter dates
from medical records, separate from DOB and other dates.

Encounter dates indicate WHEN medical services were provided (e.g., "Date of Service",
"Visit Date", "Encounter Date"), which is critical for chronological ordering of records.
"""

import os
import re
import logging
from typing import Tuple, Optional, Dict, List
from datetime import datetime, date, timedelta
import pytesseract
from pdf2image import convert_from_path

logger = logging.getLogger(__name__)


def parse_encounter_date(ocr_text: str) -> Optional[date]:
    """
    Parse clinical encounter date from medical record OCR text.
    
    This identifies the date when medical services were provided, looking for
    markers like:
    - "Date of Service:"
    - "Visit Date:"
    - "Encounter Date:"
    - "Service Date:"
    - "Appointment Date:"
    - "Exam Date:"
    - "Consultation Date:"
    
    This is DIFFERENT from DOB (patient's birth date) and should be a recent date
    (typically within the last 10 years for most records).
    
    Args:
        ocr_text: Text extracted from medical record fax
        
    Returns:
        date object representing the encounter date, or None if not found
    """
    if not ocr_text:
        logger.warning("Empty OCR text provided for encounter date parsing")
        return None
    
    # Encounter date patterns - STRICT contextual matching
    # Ordered by specificity (most explicit first)
    encounter_patterns = [
        # Pattern 1: "Date of Service: MM/DD/YYYY"
        (
            r'Date\s+of\s+Service\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Date of Service: MM/DD/YYYY"
        ),
        
        # Pattern 2: "Visit Date: MM/DD/YYYY"
        (
            r'Visit\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Visit Date: MM/DD/YYYY"
        ),
        
        # Pattern 3: "Encounter Date: MM/DD/YYYY"
        (
            r'Encounter\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Encounter Date: MM/DD/YYYY"
        ),
        
        # Pattern 4: "Service Date: MM/DD/YYYY"
        (
            r'Service\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Service Date: MM/DD/YYYY"
        ),
        
        # Pattern 5: "Appointment Date: MM/DD/YYYY"
        (
            r'Appointment\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Appointment Date: MM/DD/YYYY"
        ),
        
        # Pattern 6: "Exam Date: MM/DD/YYYY"
        (
            r'Exam\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Exam Date: MM/DD/YYYY"
        ),
        
        # Pattern 7: "Consultation Date: MM/DD/YYYY"
        (
            r'Consultation\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Consultation Date: MM/DD/YYYY"
        ),
        
        # Pattern 8: "Procedure Date: MM/DD/YYYY"
        (
            r'Procedure\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Procedure Date: MM/DD/YYYY"
        ),
        
        # Pattern 9: "Surgery Date: MM/DD/YYYY"
        (
            r'Surgery\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Surgery Date: MM/DD/YYYY"
        ),
        
        # Pattern 10: "Admission Date: MM/DD/YYYY" (for hospital records)
        (
            r'Admission\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Admission Date: MM/DD/YYYY"
        ),
        
        # Pattern 11: "Discharge Date: MM/DD/YYYY" (for hospital records)
        (
            r'Discharge\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Discharge Date: MM/DD/YYYY"
        ),
        
        # Pattern 12: "Date Seen: MM/DD/YYYY" (common in clinic notes)
        (
            r'Date\s+Seen\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
            ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"],
            "Date Seen: MM/DD/YYYY"
        ),
        
        # Pattern 13: Month name formats
        (
            r'Date\s+of\s+Service\s*[:\-–—]\s*([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})',
            ["%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"],
            "Date of Service: Month DD, YYYY"
        ),
        
        # Pattern 14: ISO format for Date of Service
        (
            r'Date\s+of\s+Service\s*[:\-–—]\s*(\d{4}-\d{2}-\d{2})',
            ["%Y-%m-%d"],
            "Date of Service: YYYY-MM-DD"
        ),
    ]
    
    today = date.today()
    ten_years_ago = today - timedelta(days=365*10)
    
    for pattern, formats, pattern_desc in encounter_patterns:
        match = re.search(pattern, ocr_text, flags=re.IGNORECASE | re.MULTILINE)
        
        if match:
            date_str = match.group(1).strip()
            
            # Try each format
            for fmt in formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt).date()
                    
                    # Validate date is reasonable for an encounter
                    # Should be:
                    # 1. In the past (not future)
                    # 2. Within last 50 years (most medical records)
                    # 3. Not a DOB (typically DOB would be 18-120 years ago)
                    
                    age_days = (today - parsed_date).days
                    
                    if 0 <= age_days <= (365 * 50):  # Last 50 years
                        logger.info(
                            f"✅ Encounter date matched with pattern '{pattern_desc}': "
                            f"{parsed_date} ({age_days // 365} years ago)"
                        )
                        return parsed_date
                    else:
                        logger.debug(
                            f"Parsed date {parsed_date} is outside reasonable "
                            f"encounter range (0-50 years ago)"
                        )
                
                except ValueError:
                    continue
    
    logger.warning("❌ Could not parse encounter date from text (no contextual markers found)")
    logger.debug(f"Searched in text snippet: {ocr_text[:500]}...")
    
    return None


def parse_all_dates(ocr_text: str) -> Dict[str, Optional[date]]:
    """
    Parse all relevant dates from a medical record.
    
    Returns:
        Dictionary with:
        - patient_dob: Patient's date of birth
        - encounter_date: Date of clinical encounter
        - first_name: Patient's first name
        - last_name: Patient's last name
    """
    # Import the existing parsing functions
    from improved_ocr import parse_name_and_dob
    
    # Parse patient info (name and DOB)
    first_name, last_name, dob = parse_name_and_dob(ocr_text)
    
    # Parse encounter date
    encounter_date = parse_encounter_date(ocr_text)
    
    result = {
        "first_name": first_name,
        "last_name": last_name,
        "patient_dob": dob,
        "encounter_date": encounter_date
    }
    
    logger.info(
        f"Parsed all dates: DOB={dob}, Encounter={encounter_date}, "
        f"Name={first_name} {last_name}"
    )
    
    return result


def extract_multiple_encounter_dates(ocr_text: str) -> List[date]:
    """
    Extract ALL encounter dates from a medical record (some records have multiple).
    
    Useful for records that span multiple visits or contain a visit history.
    
    Returns:
        List of date objects, sorted in chronological order (oldest first)
    """
    dates = []
    
    # Use all the same patterns from parse_encounter_date
    encounter_patterns = [
        (r'Date\s+of\s+Service\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', ["%m/%d/%Y", "%m/%d/%y"]),
        (r'Visit\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', ["%m/%d/%Y", "%m/%d/%y"]),
        (r'Encounter\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', ["%m/%d/%Y", "%m/%d/%y"]),
        (r'Service\s+Date\s*[:\-–—]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', ["%m/%d/%Y", "%m/%d/%y"]),
    ]
    
    today = date.today()
    
    for pattern, formats in encounter_patterns:
        matches = re.finditer(pattern, ocr_text, flags=re.IGNORECASE | re.MULTILINE)
        
        for match in matches:
            date_str = match.group(1).strip()
            
            for fmt in formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt).date()
                    
                    # Validate reasonable range
                    age_days = (today - parsed_date).days
                    if 0 <= age_days <= (365 * 50):
                        if parsed_date not in dates:  # Avoid duplicates
                            dates.append(parsed_date)
                except ValueError:
                    continue
    
    # Sort chronologically (oldest first)
    dates.sort()
    
    if dates:
        logger.info(f"Found {len(dates)} encounter date(s): {dates}")
    
    return dates


# Example usage and testing
if __name__ == "__main__":
    # Test with sample medical record text
    sample_text = """
    MASSACHUSETTS GENERAL HOSPITAL
    Medical Records Department
    
    Patient Name: John Smith
    Date of Birth: 03/15/1980
    MRN: 123456
    
    Date of Service: 11/05/2024
    Provider: Dr. Sarah Johnson
    
    Chief Complaint: Follow-up visit
    
    HISTORY OF PRESENT ILLNESS:
    Patient presents for routine follow-up...
    """
    
    result = parse_all_dates(sample_text)
    print(f"\nParsed Results:")
    print(f"  Patient: {result['first_name']} {result['last_name']}")
    print(f"  DOB: {result['patient_dob']}")
    print(f"  Encounter Date: {result['encounter_date']}")
