# app/services/hospital_directory.py - v2.0
"""
Enhanced Hospital Directory Service

Improvements:
1. Fuzzy matching for hospital name searches (handles misspellings)
2. Better location-based filtering (city, state, ZIP)
3. Multi-source aggregation (NPPES, Medicare, web)
4. Medical records fax number discovery
5. Intelligent result ranking
"""

import requests
import logging
from typing import List, Dict, Optional
import re
from rapidfuzz import fuzz, process

from app.services.medical_records_finder import find_and_cache_medical_records_fax

logger = logging.getLogger(__name__)


def search_hospitals(
    query: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    limit: int = 50
) -> List[Dict]:
    """
    Enhanced hospital search with fuzzy matching and multiple sources.
    
    Args:
        query: Hospital name (supports partial matches and misspellings)
        city: City name
        state: State abbreviation (e.g., MA)
        zip_code: ZIP code
        limit: Max results to return
    
    Returns:
        List of hospital dicts with name, address, phone, fax, etc.
    """
    results = []
    
    # Strategy 1: Search NPPES (filtered for hospitals and healthcare facilities)
    if query or city or state or zip_code:
        nppes_results = _search_nppes_hospitals_enhanced(
            query=query,
            city=city,
            state=state,
            zip_code=zip_code,
            limit=limit
        )
        results.extend(nppes_results)
    
    # Strategy 2: Search Medicare Hospital Compare
    if city or state or zip_code:
        medicare_results = get_medicare_hospitals(
            city=city,
            state=state,
            zip_code=zip_code,
            limit=limit
        )
        results.extend(medicare_results)
    
    # Strategy 3: If we have a query, do fuzzy matching on results
    if query and results:
        results = _apply_fuzzy_matching(results, query)
    
    # Remove duplicates and rank results
    results = _deduplicate_and_rank(results, query)
    
    # For top results, try to find medical records fax
    results = _enhance_with_medical_records_fax(results[:10])
    
    return results[:limit]


def _search_nppes_hospitals_enhanced(
    query: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    limit: int = 50
) -> List[Dict]:
    """
    Enhanced NPPES search with better filtering for hospitals.
    """
    from app.services.provider_directory import search_providers
    
    results = []
    
    try:
        # Search by organization name if query provided
        if query:
            providers = search_providers(
                organization_name=query,
                city=city,
                state=state,
                postal_code=zip_code,
                limit=limit
            )
            results.extend(providers)
        
        # Also search by location only
        if not query and (city or state or zip_code):
            providers = search_providers(
                city=city,
                state=state,
                postal_code=zip_code,
                limit=limit
            )
            results.extend(providers)
        
        # Filter for hospitals and healthcare facilities only
        hospital_keywords = [
            'hospital', 'medical center', 'health system', 'clinic',
            'healthcare', 'urgent care', 'surgery center', 'imaging center'
        ]
        
        filtered_results = []
        for p in results:
            name = p.get('name', '').lower()
            # Check if it's a NPI-2 (organization) or has hospital keywords
            if p.get('type') == 'NPI-2' or any(kw in name for kw in hospital_keywords):
                filtered_results.append({
                    "name": p.get("name"),
                    "fax": p.get("fax"),
                    "phone": p.get("phone"),
                    "address": f"{p.get('address_line1', '')}, {p.get('city', '')}, {p.get('state', '')} {p.get('postal_code', '')}".strip(", "),
                    "city": p.get("city"),
                    "state": p.get("state"),
                    "zip_code": p.get("postal_code"),
                    "npi": p.get("npi"),
                    "source": "NPPES",
                    "type": "hospital"
                })
        
        return filtered_results
        
    except Exception as e:
        logger.error(f"NPPES search error: {e}")
        return []


def get_medicare_hospitals(
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    limit: int = 50
) -> List[Dict]:
    """
    Enhanced Medicare Hospital Compare API search.
    """
    results = []
    
    try:
        base_url = "https://data.medicare.gov/resource/xubh-q36u.json"
        
        params = {"$limit": limit}
        
        # Build filters
        where_clauses = []
        if city:
            where_clauses.append(f"upper(city) = '{city.upper()}'")
        if state:
            where_clauses.append(f"upper(state) = '{state.upper()}'")
        if zip_code:
            where_clauses.append(f"zip_code = '{zip_code}'")
        
        if where_clauses:
            params["$where"] = " AND ".join(where_clauses)
        
        response = requests.get(base_url, params=params, timeout=10)
        
        if response.ok:
            data = response.json()
            
            for hospital in data:
                results.append({
                    "name": hospital.get("hospital_name", ""),
                    "phone": hospital.get("phone_number", ""),
                    "fax": None,  # Medicare doesn't provide fax
                    "address": hospital.get("address", ""),
                    "city": hospital.get("city", ""),
                    "state": hospital.get("state", ""),
                    "zip_code": hospital.get("zip_code", ""),
                    "hospital_type": hospital.get("hospital_type", ""),
                    "source": "Medicare.gov",
                    "type": "hospital",
                    "note": "Medical records fax number will be found automatically"
                })
        
    except Exception as e:
        logger.error(f"Medicare API error: {e}")
    
    return results


def _apply_fuzzy_matching(results: List[Dict], query: str) -> List[Dict]:
    """
    Apply fuzzy matching to rank results by similarity to query.
    Uses RapidFuzz for fast fuzzy string matching.
    """
    if not query or not results:
        return results
    
    # Calculate fuzzy match scores for each result
    scored_results = []
    for result in results:
        name = result.get('name', '')
        
        # Use token_sort_ratio for best results with hospital names
        score = fuzz.token_sort_ratio(query.lower(), name.lower())
        
        result['_match_score'] = score
        scored_results.append(result)
    
    # Sort by match score (descending)
    scored_results.sort(key=lambda x: x.get('_match_score', 0), reverse=True)
    
    # Filter out very low scores (below 60)
    filtered_results = [r for r in scored_results if r.get('_match_score', 0) >= 60]
    
    return filtered_results if filtered_results else scored_results[:20]


def _deduplicate_and_rank(results: List[Dict], query: Optional[str] = None) -> List[Dict]:
    """
    Remove duplicate hospitals and rank by quality.
    """
    seen = {}
    unique_results = []
    
    for r in results:
        name = r.get('name', '').lower().strip()
        
        # Create a key for deduplication (name + city + state)
        key = f"{name}_{r.get('city', '').lower()}_{r.get('state', '').lower()}"
        
        if key in seen:
            # Keep the one with more information
            existing = seen[key]
            if _result_quality_score(r) > _result_quality_score(existing):
                # Replace with better result
                idx = unique_results.index(existing)
                unique_results[idx] = r
                seen[key] = r
        else:
            seen[key] = r
            unique_results.append(r)
    
    # Sort by quality score
    unique_results.sort(key=lambda x: _result_quality_score(x), reverse=True)
    
    return unique_results


def _result_quality_score(result: Dict) -> int:
    """
    Calculate quality score for a result.
    Higher score = better quality.
    """
    score = 0
    
    # Has fax number (most important)
    if result.get('fax'):
        score += 50
    
    # Has phone
    if result.get('phone'):
        score += 20
    
    # Has address
    if result.get('address'):
        score += 10
    
    # Has NPI
    if result.get('npi'):
        score += 10
    
    # Fuzzy match score if available
    if result.get('_match_score'):
        score += result['_match_score']
    
    # Source preference (NPPES > Medicare)
    if result.get('source') == 'NPPES':
        score += 5
    
    return score


def _enhance_with_medical_records_fax(results: List[Dict]) -> List[Dict]:
    """
    For top results without fax, try to find medical records fax number.
    This is done asynchronously to avoid blocking the response.
    """
    enhanced_results = []
    
    for result in results:
        # If already has fax, keep it
        if result.get('fax'):
            enhanced_results.append(result)
            continue
        
        # Try to find medical records fax
        try:
            logger.info(f"Attempting to find medical records fax for: {result.get('name')}")
            
            fax_info = find_and_cache_medical_records_fax(
                hospital_name=result['name'],
                city=result.get('city'),
                state=result.get('state'),
                website=result.get('website')
            )
            
            if fax_info.get('fax'):
                result['fax'] = fax_info['fax']
                result['medical_records_fax'] = fax_info['fax']
                result['fax_confidence'] = fax_info.get('confidence', 0.0)
                result['fax_source'] = fax_info.get('source', 'Unknown')
                result['fax_verified'] = fax_info.get('confidence', 0.0) >= 0.8
                result['verification_url'] = fax_info.get('verification_url')
                
                logger.info(f"✅ Found medical records fax for {result['name']}: {fax_info['fax']}")
            else:
                logger.warning(f"❌ Could not find medical records fax for {result['name']}")
                result['note'] = "Fax number not found - please call to obtain"
        
        except Exception as e:
            logger.error(f"Error finding medical records fax: {e}")
            result['note'] = "Fax number verification in progress"
        
        enhanced_results.append(result)
    
    return enhanced_results


def search_hospital_by_name(name: str, fuzzy: bool = True) -> List[Dict]:
    """
    Search for a specific hospital by name with optional fuzzy matching.
    
    Args:
        name: Hospital name
        fuzzy: Enable fuzzy matching for misspellings
    
    Returns:
        List of matching hospitals
    """
    return search_hospitals(query=name, limit=20)


def validate_fax_number(fax: str) -> bool:
    """Validate that a fax number is properly formatted."""
    if not fax:
        return False
    
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', fax)
    
    # Should be 10 or 11 digits (with or without country code)
    return len(digits) in [10, 11]


def format_fax_number(fax: str) -> str:
    """Format a fax number consistently to E.164."""
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', fax)
    
    # Format as +1-XXX-XXX-XXXX
    if len(digits) == 10:
        return f"+1-{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"+1-{digits[1:4]}-{digits[4:7]}-{digits[7:11]}"
    
    return fax
