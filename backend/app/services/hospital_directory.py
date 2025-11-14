# app/services/hospital_directory.py - v4.3 - FIXED: Don't fuzzy match wildcard searches
"""
Hospital/Facility Search - Fixed Fuzzy Matching Logic

FIXED IN v4.3:
- Don't apply fuzzy matching when using wildcard searches (they're already broad!)
- Wildcard searches trust NPPES API results
- Only fuzzy match for specific, longer queries
- Much better results for short queries like "Mayo", "Cleveland", etc.
"""

import requests
import logging
import re
from typing import List, Dict, Optional
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

# NPPES API endpoint
NPPES_API = "https://npiregistry.cms.hhs.gov/api/"

# Hospital-related keywords for filtering
HOSPITAL_KEYWORDS = [
    'hospital', 'medical center', 'health system', 'healthcare',
    'clinic', 'medical group', 'health center', 'regional medical',
    'community hospital', 'general hospital', 'memorial', 'medicine',
    'university hospital', 'children\'s hospital', 'veterans',
    'surgery center', 'urgent care', 'emergency', 'trauma center',
    'medical', 'physicians', 'associates', 'care', 'health'
]


def validate_fax_number(fax: str) -> bool:
    """Validate that a fax number is properly formatted."""
    if not fax:
        return False
    digits = re.sub(r'\D', '', fax)
    return len(digits) == 10 or len(digits) == 11


def format_fax_number(fax: str) -> str:
    """Format a fax number to E.164 format (+1XXXXXXXXXX)."""
    if not fax:
        return ""
    digits = re.sub(r'\D', '', fax)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    if fax.startswith('+'):
        return fax
    return f"+1{digits}"


def _is_hospital_like(name: str) -> bool:
    """Check if organization name suggests it's a hospital or medical facility."""
    if not name:
        return False
    name_lower = name.lower()
    return any(keyword in name_lower for keyword in HOSPITAL_KEYWORDS)


def _fuzzy_match_hospitals(query: str, candidates: List[Dict], threshold: int = 40) -> List[Dict]:
    """
    Perform fuzzy matching on hospital names.

    Uses token_sort_ratio for flexible matching that handles:
    - Misspellings
    - Partial names
    - Word order differences
    """
    if not query or not candidates:
        return candidates

    logger.info(f"🔍 Applying fuzzy matching with query: '{query}' (threshold: {threshold})")

    # Extract names for matching
    names = [c['name'] for c in candidates]

    # Use process.extract to get all matches above threshold
    matches = process.extract(
        query,
        names,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=threshold,
        limit=None
    )

    # Create a mapping of names to scores
    score_map = {match[0]: match[1] for match in matches}

    # Filter and sort candidates by score
    matched_candidates = []
    for candidate in candidates:
        if candidate['name'] in score_map:
            candidate['fuzzy_score'] = score_map[candidate['name']]
            matched_candidates.append(candidate)

    matched_candidates.sort(key=lambda x: x.get('fuzzy_score', 0), reverse=True)

    logger.info(f"✅ Fuzzy matching kept {len(matched_candidates)} of {len(candidates)} results")

    return matched_candidates


def search_hospitals(
        query: Optional[str] = None,
        zip_code: Optional[str] = None,
        limit: int = 200,
        use_fuzzy: bool = True,
        fuzzy_threshold: int = 10
) -> List[Dict]:
    """
    Search for hospitals and medical facilities using NPPES API.

    FIXED v4.3: Don't apply fuzzy matching to wildcard searches
    - Wildcard searches ("Mayo*") already cast a broad net
    - Only fuzzy match longer, specific queries
    - Much better results for short queries

    Args:
        query: Hospital/facility name to search for
        zip_code: ZIP/postal code for location filtering
        limit: Maximum number of results (default 200, API max 1200)
        use_fuzzy: Whether to apply fuzzy matching (default True)
        fuzzy_threshold: Minimum fuzzy match score 0-100 (default 40)

    Returns:
        List of facility dictionaries with name, address, phone, fax, etc.
    """
    logger.info("=" * 80)
    logger.info("🏥 HOSPITAL SEARCH STARTED")
    logger.info(f"   Query: '{query}'")
    logger.info(f"   ZIP Code: '{zip_code}'")
    logger.info(f"   Limit: {limit}")
    logger.info(f"   Fuzzy Matching: {use_fuzzy} (threshold: {fuzzy_threshold})")
    logger.info("=" * 80)

    # Validate inputs
    if not query and not zip_code:
        logger.warning("❌ No search criteria provided")
        return []

    # Build NPPES API parameters
    params = {
        "version": "2.1",
        "limit": min(limit, 1200),
    }

    # Track if we used wildcard
    used_wildcard = False

    # Organization name search with wildcard
    if query:
        clean_query = query.strip()

        # NPPES supports trailing wildcards with 2+ characters
        # Use wildcard for short, single-word queries
        if len(clean_query.split()) == 1 and len(clean_query) >= 2 and not clean_query.endswith('*'):
            search_term = f"{clean_query}*"
            used_wildcard = True
            logger.info(f"🎯 Using wildcard search: '{search_term}'")
        else:
            search_term = clean_query
            logger.info(f"🎯 Searching for: '{search_term}'")

        params["organization_name"] = search_term

    # ZIP code filtering
    if zip_code:
        clean_zip = re.sub(r'\D', '', zip_code)
        if clean_zip:
            params["postal_code"] = clean_zip[:5]
            logger.info(f"📍 Filtering by ZIP: '{params['postal_code']}'")
            if not query:
                params["enumeration_type"] = "NPI-2"

    # Make NPPES API request
    try:
        logger.info("📡 Making NPPES API request...")
        logger.info(f"   URL: {NPPES_API}")
        logger.info(f"   Full params: {params}")

        response = requests.get(NPPES_API, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        result_count = data.get("result_count", 0)
        logger.info(f"✅ NPPES API SUCCESS")
        logger.info(f"   HTTP Status: {response.status_code}")
        logger.info(f"   Results from API: {result_count}")

        if result_count == 0:
            logger.warning("⚠️  NPPES returned 0 results")
            logger.warning(f"   Try: Simplifying query or searching by ZIP")
            return []

    except requests.exceptions.Timeout:
        logger.error("❌ NPPES API TIMEOUT after 30 seconds")
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
    results_raw = data.get("results", [])
    logger.info(f"📦 Processing {len(results_raw)} raw results...")

    hospitals = []
    filtered_by_type = 0
    filtered_by_keyword = 0
    no_address = 0

    for result in results_raw:
        try:
            enum_type = result.get("enumeration_type", "")

            # Get organization name
            basic = result.get("basic", {})
            name = basic.get("organization_name", "").strip()

            # For NPI-1 (individuals), try to get name
            if not name and enum_type == "NPI-1":
                first = basic.get("first_name", "")
                last = basic.get("last_name", "")
                if first and last:
                    name = f"{first} {last}"

            if not name:
                continue

            # Filter by enumeration type for name searches
            if query and enum_type == "NPI-1":
                if not _is_hospital_like(name):
                    filtered_by_type += 1
                    continue

            # Filter by medical keywords
            if query and not _is_hospital_like(name):
                logger.debug(f"⏭️  Not medical: {name}")
                filtered_by_keyword += 1
                continue

            # Get NPI
            npi = result.get("number", "")

            # Get addresses
            addresses = result.get("addresses", [])
            practice_addr = None
            mailing_addr = None

            for addr in addresses:
                if addr.get("address_purpose") == "LOCATION":
                    practice_addr = addr
                elif addr.get("address_purpose") == "MAILING":
                    mailing_addr = addr

            address = practice_addr or mailing_addr
            if not address:
                no_address += 1
                continue

            # Extract address details
            address_line1 = address.get("address_1", "").strip()
            city = address.get("city", "").strip()
            state = address.get("state", "").strip()
            postal_code = address.get("postal_code", "").strip()
            phone = address.get("telephone_number", "").strip()
            fax = address.get("fax_number", "").strip()

            # Build hospital dictionary
            hospital = {
                "name": name,
                "npi": npi,
                "address": address_line1,
                "city": city,
                "state": state,
                "zip": postal_code,
                "phone": phone,
                "fax": fax,
                "source": "NPPES",
                "has_fax": bool(fax),
                "fuzzy_score": 100  # Default high score
            }

            hospitals.append(hospital)

        except Exception as e:
            logger.error(f"❌ Error parsing result: {e}")
            continue

    logger.info(f"✅ Parsed {len(hospitals)} medical facilities")
    logger.info(
        f"   Filtered: {filtered_by_type} individuals, {filtered_by_keyword} non-medical, {no_address} no-address")

    # FIXED v4.3: Only apply fuzzy matching if we didn't use wildcard
    # Wildcard searches already cast a broad net, trust the API results
    if query and use_fuzzy and not used_wildcard and hospitals:
        logger.info(f"   Applying fuzzy matching (query didn't use wildcard)")
        hospitals = _fuzzy_match_hospitals(query, hospitals, threshold=fuzzy_threshold)
    elif used_wildcard:
        logger.info(f"   ⏭️  Skipping fuzzy matching (wildcard search already broad)")

    # Sort results: prioritize fax, then by name
    hospitals.sort(key=lambda x: (not x['has_fax'], x['name'].lower()))

    logger.info(f"🎉 Returning {len(hospitals)} final results")
    logger.info(f"   With fax: {sum(1 for h in hospitals if h['has_fax'])}")
    logger.info(f"   Without fax: {sum(1 for h in hospitals if not h['has_fax'])}")
    logger.info("=" * 80)

    return hospitals


def format_search_results_for_display(hospitals: List[Dict], page: int = 1, per_page: int = 20) -> Dict:
    """Format search results for paginated display."""
    total_results = len(hospitals)
    total_pages = (total_results + per_page - 1) // per_page

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_results = hospitals[start_idx:end_idx]

    return {
        "results": page_results,
        "page": page,
        "per_page": per_page,
        "total_results": total_results,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "start_idx": start_idx + 1 if page_results else 0,
        "end_idx": min(end_idx, total_results)
    }


# Cache for search results
_search_cache = {}


def cache_search_results(search_key: str, results: List[Dict]) -> None:
    """Cache search results for pagination."""
    _search_cache[search_key] = results
    logger.debug(f"💾 Cached {len(results)} results for key: {search_key}")


def get_cached_search_results(search_key: str) -> Optional[List[Dict]]:
    """Retrieve cached search results."""
    results = _search_cache.get(search_key)
    if results:
        logger.debug(f"💾 Retrieved {len(results)} results from cache")
    return results


def clear_search_cache():
    """Clear all cached search results."""
    _search_cache.clear()
    logger.debug("💾 Search cache cleared")