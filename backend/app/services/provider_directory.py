# app/services/provider_directory.py - IMPROVED with Error Handling

import requests
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

NPPES_URL = "https://npiregistry.cms.hhs.gov/api/"


def _nppes_get(params: Dict) -> Dict:
    """Make a request to the NPPES API with proper error handling."""
    params = {"version": "2.1", **params}

    logger.info(f"🔍 NPPES API request with params: {params}")

    try:
        r = requests.get(NPPES_URL, params=params, timeout=20)
        r.raise_for_status()
        response_data = r.json()

        result_count = response_data.get("result_count", 0)
        logger.info(f"✅ NPPES API returned {result_count} results")

        return response_data

    except requests.exceptions.Timeout as e:
        logger.error(f"❌ NPPES API timeout: {e}")
        raise
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ NPPES API connection error: {e}")
        raise
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ NPPES API HTTP error: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        logger.exception(f"❌ NPPES API unexpected error: {e}")
        raise


def search_providers(
        *,
        city: Optional[str] = None,
        state: Optional[str] = None,
        postal_code: Optional[str] = None,
        organization_name: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        limit: int = 25
) -> List[Dict]:
    """
    Search for healthcare providers using the NPPES API.

    Args:
        city: City name
        state: State abbreviation (e.g., 'MA')
        postal_code: ZIP code
        organization_name: Organization name to search
        first_name: Provider first name
        last_name: Provider last name
        limit: Maximum number of results

    Returns:
        List of provider dictionaries
    """
    # Build request parameters
    params = {"limit": limit}

    if city:
        params["city"] = city
    if state:
        params["state"] = state
    if postal_code:
        params["postal_code"] = postal_code
    if organization_name:
        params["organization_name"] = organization_name
    if first_name:
        params["first_name"] = first_name
    if last_name:
        params["last_name"] = last_name

    logger.info(
        f"🔍 Searching providers: "
        f"city={city}, state={state}, postal_code={postal_code}, "
        f"org={organization_name}, limit={limit}"
    )

    # Make API request with error handling
    try:
        data = _nppes_get(params)
    except Exception as e:
        logger.error(f"❌ Provider search failed: {e}")
        # Return empty list but log the error
        return []

    # Parse results
    out = []
    for res in data.get("results", []):
        addresses = res.get("addresses", [])

        # Get LOCATION address (primary practice location)
        location = None
        if addresses:
            location = next(
                (a for a in addresses if a.get("address_purpose") == "LOCATION"),
                {}
            )

        if not location:
            location = {}

        # Extract contact information
        fax = location.get("fax_number") or None
        phone = location.get("telephone_number") or None
        city_val = location.get("city")
        state_val = location.get("state")
        postal = location.get("postal_code")
        address_line1 = location.get("address_1", "")
        address_line2 = location.get("address_2", "")

        # Get provider/organization name
        name = None
        basic = res.get("basic", {})

        if basic.get("organization_name"):
            name = basic["organization_name"]
        else:
            first = basic.get("first_name") or ""
            last = basic.get("last_name") or ""
            name = (first + " " + last).strip()

        npi = res.get("number")

        # Determine if this is an organization (NPI-2) or individual (NPI-1)
        enumeration_type = res.get("enumeration_type", "")
        provider_type = "NPI-2" if enumeration_type == "NPI-2" else "NPI-1"

        # Build result dictionary
        provider_dict = {
            "npi": npi,
            "name": name,
            "type": provider_type,
            "fax": fax,
            "phone": phone,
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": city_val,
            "state": state_val,
            "postal_code": postal,
        }

        out.append(provider_dict)

    logger.info(f"✅ Parsed {len(out)} providers from NPPES results")

    return out