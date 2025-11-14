# app/services/hospital_directory.py - v3.0 - SIMPLIFIED FROM SCRATCH
"""
Hospital/Facility Search - Simplified Version

FOCUS: Only search for organizations (hospitals, clinics, medical centers)
EXCLUDE: Individual doctors/practitioners

Key Features:
- Searches NPPES for organizations only (NPI-2)
- Simple, straightforward logic
- Comprehensive logging
- No complex filtering or fuzzy matching initially
"""

import requests
import logging
from typing import List, Dict, Optional
import re

logger = logging.getLogger(__name__)

# NPPES API endpoint
NPPES_API = "https://npiregistry.cms.hhs.gov/api/"


def search_hospitals(
        query: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zip_code: Optional[str] = None,
        limit: int = 50
) -> List[Dict]:
    """
    Search for hospitals and medical facilities (organizations only).

    This function focuses on returning healthcare FACILITIES, not individual doctors.

    Args:
        query: Hospital/facility name to search for
        city: City name
        state: State code (e.g., 'MA', 'CA')
        zip_code: ZIP/postal code
        limit: Maximum number of results (default 50)

    Returns:
        List of facility dictionaries with name, address, phone, fax, etc.
    """
    logger.info("=" * 80)
    logger.info(f"🏥 HOSPITAL SEARCH STARTED")
    logger.info(f"   Query: '{query}'")
    logger.info(f"   City: '{city}'")
    logger.info(f"   State: '{state}'")
    logger.info(f"   ZIP: '{zip_code}'")
    logger.info(f"   Limit: {limit}")
    logger.info("=" * 80)

    # Build NPPES API parameters
    params = {
        "version": "2.1",
        "limit": limit,
        "enumeration_type": "NPI-2"  # CRITICAL: Only organizations, not individuals
    }

    # Add search criteria
    if query:
        params["organization_name"] = query
        logger.info(f"📝 Searching by organization name: '{query}'")

    if city:
        params["city"] = city
        logger.info(f"📍 Filtering by city: '{city}'")

    if state:
        params["state"] = state
        logger.info(f"📍 Filtering by state: '{state}'")

    if zip_code:
        params["postal_code"] = zip_code
        logger.info(f"📍 Filtering by ZIP: '{zip_code}'")

    # Make NPPES API request
    try:
        logger.info(f"🌐 Making NPPES API request...")
        logger.info(f"   URL: {NPPES_API}")
        logger.info(f"   Params: {params}")

        response = requests.get(NPPES_API, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        result_count = data.get("result_count", 0)

        logger.info(f"✅ NPPES API SUCCESS")
        logger.info(f"   Status: {response.status_code}")
        logger.info(f"   Total results: {result_count}")

    except requests.exceptions.Timeout:
        logger.error(f"❌ NPPES API TIMEOUT after 30 seconds")
        return []
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ NPPES API CONNECTION ERROR: {e}")
        return []
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ NPPES API HTTP ERROR: {e.response.status_code}")
        logger.error(f"   Response: {e.response.text[:500]}")
        return []
    except Exception as e:
        logger.exception(f"❌ NPPES API UNEXPECTED ERROR: {e}")
        return []

    # Parse results
    results = data.get("results", [])

    if not results:
        logger.warning(f"⚠️ No results returned from NPPES API")
        return []

    logger.info(f"📊 Processing {len(results)} results from NPPES...")

    facilities = []
    for idx, result in enumerate(results, 1):
        try:
            facility = _parse_nppes_result(result, idx)
            if facility:
                facilities.append(facility)
                logger.debug(f"   ✓ Parsed facility {idx}: {facility['name']}")
        except Exception as e:
            logger.warning(f"   ⚠️ Failed to parse result {idx}: {e}")
            continue

    logger.info(f"✅ Successfully parsed {len(facilities)} facilities")
    logger.info("=" * 80)

    return facilities


def _parse_nppes_result(result: Dict, index: int) -> Optional[Dict]:
    """
    Parse a single NPPES result into our facility format.

    Args:
        result: Raw NPPES result dictionary
        index: Result number (for logging)

    Returns:
        Facility dictionary or None if parsing fails
    """
    try:
        # Get basic information
        npi = result.get("number")
        basic = result.get("basic", {})
        org_name = basic.get("organization_name", "")

        if not org_name:
            logger.debug(f"   ⚠️ Result {index}: No organization name, skipping")
            return None

        # Get addresses (prefer LOCATION, fallback to MAILING)
        addresses = result.get("addresses", [])

        location_address = None
        mailing_address = None

        for addr in addresses:
            purpose = addr.get("address_purpose", "")
            if purpose == "LOCATION":
                location_address = addr
            elif purpose == "MAILING":
                mailing_address = addr

        # Use LOCATION address if available, otherwise MAILING
        address = location_address or mailing_address

        if not address:
            logger.debug(f"   ⚠️ Result {index}: No address found, skipping")
            return None

        # Extract address details
        address_line1 = address.get("address_1", "")
        address_line2 = address.get("address_2", "")
        city = address.get("city", "")
        state = address.get("state", "")
        postal_code = address.get("postal_code", "")
        phone = address.get("telephone_number")
        fax = address.get("fax_number")

        # Format full address string
        full_address_parts = [address_line1]
        if address_line2:
            full_address_parts.append(address_line2)
        full_address_parts.extend([city, state, postal_code])
        full_address = ", ".join(filter(None, full_address_parts))

        # Build facility dictionary
        facility = {
            "name": org_name,
            "npi": npi,
            "address": full_address,
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": city,
            "state": state,
            "zip_code": postal_code,
            "phone": phone,
            "fax": fax,
            "source": "NPPES",
            "type": "organization"
        }

        return facility

    except Exception as e:
        logger.warning(f"   ⚠️ Error parsing result {index}: {e}")
        return None


def validate_fax_number(fax: str) -> bool:
    """
    Validate that a fax number is properly formatted.

    Args:
        fax: Fax number string

    Returns:
        True if valid, False otherwise
    """
    if not fax:
        return False

    # Remove all non-digit characters
    digits = re.sub(r'\D', '', fax)

    # Should be 10 or 11 digits (with or without country code)
    return len(digits) in [10, 11]


def format_fax_number(fax: str) -> str:
    """
    Format a fax number consistently to E.164 format.

    Args:
        fax: Raw fax number

    Returns:
        Formatted fax number (+1-XXX-XXX-XXXX)
    """
    if not fax:
        return fax

    # Remove all non-digit characters
    digits = re.sub(r'\D', '', fax)

    # Format as +1-XXX-XXX-XXXX
    if len(digits) == 10:
        return f"+1-{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"+1-{digits[1:4]}-{digits[4:7]}-{digits[7:11]}"

    return fax


# Compatibility function for existing code
def search_hospital_by_name(name: str, fuzzy: bool = True) -> List[Dict]:
    """
    Search for hospitals by name (compatibility wrapper).

    Args:
        name: Hospital name to search for
        fuzzy: Ignored (for compatibility)

    Returns:
        List of matching facilities
    """
    return search_hospitals(query=name, limit=20)