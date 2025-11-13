# app/services/medical_records_finder.py - v1.0
"""
Medical Records Fax Number Discovery Service

This service intelligently finds medical records department fax numbers through:
1. Web scraping hospital medical records request forms
2. Targeted Google searches for medical records departments
3. Pattern matching in hospital websites
4. Caching verified numbers for future use
"""

import logging
import re
import requests
from typing import Optional, Dict, List, Tuple
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin
import time

logger = logging.getLogger(__name__)

# Common patterns for finding medical records fax numbers
FAX_PATTERNS = [
    r'medical\s+records?\s+fax[:\s]+(\+?1?[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})',
    r'health\s+information\s+management\s+fax[:\s]+(\+?1?[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})',
    r'him\s+department\s+fax[:\s]+(\+?1?[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})',
    r'release\s+of\s+information\s+fax[:\s]+(\+?1?[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})',
    r'roi\s+fax[:\s]+(\+?1?[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})',
]

# Keywords that indicate medical records department
MEDICAL_RECORDS_KEYWORDS = [
    'medical records',
    'health information management',
    'him department',
    'release of information',
    'roi',
    'patient records',
    'record request',
    'authorization form',
]


class MedicalRecordsFinder:
    """Service for finding and verifying medical records fax numbers."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'VeritasOne Medical Records Request Service/1.0 (HIPAA Compliant)'
        })
    
    def find_medical_records_fax(
        self, 
        hospital_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        website: Optional[str] = None
    ) -> Dict:
        """
        Main method to find medical records fax number.
        
        Returns dict with:
        - fax: str or None
        - confidence: float (0-1)
        - source: str (where it was found)
        - verification_url: str (URL where it was found)
        - method: str (how it was found)
        """
        logger.info(f"Searching medical records fax for: {hospital_name}")
        
        # Strategy 1: Search hospital website directly if provided
        if website:
            result = self._search_hospital_website(website, hospital_name)
            if result['fax']:
                return result
        
        # Strategy 2: Google search for medical records request form
        result = self._google_search_medical_records_form(hospital_name, city, state)
        if result['fax']:
            return result
        
        # Strategy 3: Search for HIM department page
        result = self._google_search_him_department(hospital_name, city, state)
        if result['fax']:
            return result
        
        # Strategy 4: Search hospital's general site for medical records info
        result = self._find_hospital_website_and_search(hospital_name, city, state)
        if result['fax']:
            return result
        
        logger.warning(f"Could not find medical records fax for {hospital_name}")
        return {
            'fax': None,
            'confidence': 0.0,
            'source': 'Not found',
            'verification_url': None,
            'method': 'exhausted_all_strategies'
        }
    
    def _search_hospital_website(self, website: str, hospital_name: str) -> Dict:
        """Search the hospital's website for medical records fax."""
        logger.info(f"Searching website: {website}")
        
        # Common paths for medical records info
        common_paths = [
            '/medical-records',
            '/health-information-management',
            '/patients/medical-records',
            '/patients/records',
            '/for-patients/medical-records',
            '/services/medical-records',
            '/release-of-information',
        ]
        
        for path in common_paths:
            try:
                url = urljoin(website, path)
                response = self.session.get(url, timeout=10, allow_redirects=True)
                
                if response.status_code == 200:
                    fax = self._extract_fax_from_html(response.text)
                    if fax:
                        return {
                            'fax': fax,
                            'confidence': 0.9,
                            'source': 'Hospital Website',
                            'verification_url': url,
                            'method': 'direct_website_search'
                        }
            except Exception as e:
                logger.debug(f"Error checking {url}: {e}")
                continue
        
        return {'fax': None, 'confidence': 0.0, 'source': None, 'verification_url': None, 'method': None}
    
    def _google_search_medical_records_form(
        self, 
        hospital_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None
    ) -> Dict:
        """Use Google to find medical records request forms."""
        logger.info(f"Google searching for medical records form: {hospital_name}")
        
        # Build search query
        location = f"{city} {state}" if city and state else ""
        queries = [
            f'"{hospital_name}" medical records request form fax {location}',
            f'"{hospital_name}" health information management fax {location}',
            f'"{hospital_name}" release of information fax {location}',
        ]
        
        for query in queries:
            try:
                results = self._perform_google_search(query, num_results=5)
                
                for url in results:
                    fax = self._scrape_page_for_fax(url)
                    if fax:
                        return {
                            'fax': fax,
                            'confidence': 0.85,
                            'source': 'Medical Records Form',
                            'verification_url': url,
                            'method': 'google_search_form'
                        }
                        
            except Exception as e:
                logger.debug(f"Error in Google search: {e}")
                continue
        
        return {'fax': None, 'confidence': 0.0, 'source': None, 'verification_url': None, 'method': None}
    
    def _google_search_him_department(
        self,
        hospital_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None
    ) -> Dict:
        """Search specifically for HIM department pages."""
        logger.info(f"Searching for HIM department: {hospital_name}")
        
        location = f"{city} {state}" if city and state else ""
        query = f'"{hospital_name}" "health information management" OR "HIM department" contact {location}'
        
        try:
            results = self._perform_google_search(query, num_results=5)
            
            for url in results:
                fax = self._scrape_page_for_fax(url)
                if fax:
                    return {
                        'fax': fax,
                        'confidence': 0.8,
                        'source': 'HIM Department Page',
                        'verification_url': url,
                        'method': 'google_search_him'
                    }
        except Exception as e:
            logger.debug(f"Error searching HIM department: {e}")
        
        return {'fax': None, 'confidence': 0.0, 'source': None, 'verification_url': None, 'method': None}
    
    def _find_hospital_website_and_search(
        self,
        hospital_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None
    ) -> Dict:
        """Find hospital website first, then search it."""
        logger.info(f"Finding website for: {hospital_name}")
        
        # Search for hospital website
        location = f"{city} {state}" if city and state else ""
        query = f'"{hospital_name}" official website {location}'
        
        try:
            results = self._perform_google_search(query, num_results=3)
            
            if results:
                website = results[0]
                return self._search_hospital_website(website, hospital_name)
        except Exception as e:
            logger.debug(f"Error finding hospital website: {e}")
        
        return {'fax': None, 'confidence': 0.0, 'source': None, 'verification_url': None, 'method': None}
    
    def _perform_google_search(self, query: str, num_results: int = 10) -> List[str]:
        """
        Perform a Google search and return URLs.
        
        Note: In production, use Google Custom Search API.
        For development, this is a placeholder that you should replace.
        """
        logger.warning("Google Custom Search API not configured - using placeholder")
        
        # TODO: Implement actual Google Custom Search API
        # Example implementation:
        # import os
        # api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        # cx = os.getenv("GOOGLE_SEARCH_CX")
        # if api_key and cx:
        #     url = "https://www.googleapis.com/customsearch/v1"
        #     params = {
        #         "key": api_key,
        #         "cx": cx,
        #         "q": query,
        #         "num": num_results
        #     }
        #     response = requests.get(url, params=params)
        #     if response.ok:
        #         data = response.json()
        #         return [item['link'] for item in data.get('items', [])]
        
        return []
    
    def _scrape_page_for_fax(self, url: str) -> Optional[str]:
        """Scrape a web page for medical records fax number."""
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                return None
            
            return self._extract_fax_from_html(response.text)
            
        except Exception as e:
            logger.debug(f"Error scraping {url}: {e}")
            return None
    
    def _extract_fax_from_html(self, html: str) -> Optional[str]:
        """Extract medical records fax from HTML content."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text()
            
            # Look for medical records section first
            for keyword in MEDICAL_RECORDS_KEYWORDS:
                # Find text containing the keyword
                pattern = re.compile(rf'.{{0,200}}{re.escape(keyword)}.{{0,200}}', re.IGNORECASE)
                matches = pattern.findall(text)
                
                for match in matches:
                    # Look for fax number in this section
                    for fax_pattern in FAX_PATTERNS:
                        fax_match = re.search(fax_pattern, match, re.IGNORECASE)
                        if fax_match:
                            fax = fax_match.group(1)
                            return self._normalize_fax_number(fax)
            
            # If no contextual match, look for any medical records fax pattern
            for pattern in FAX_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    fax = match.group(1)
                    return self._normalize_fax_number(fax)
            
        except Exception as e:
            logger.debug(f"Error extracting fax from HTML: {e}")
        
        return None
    
    def _normalize_fax_number(self, fax: str) -> str:
        """Normalize fax number to E.164 format."""
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', fax)
        
        # Format as +1-XXX-XXX-XXXX
        if len(digits) == 10:
            return f"+1-{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
        elif len(digits) == 11 and digits[0] == '1':
            return f"+1-{digits[1:4]}-{digits[4:7]}-{digits[7:11]}"
        
        return fax
    
    def verify_fax_number(self, fax: str) -> bool:
        """
        Verify that a fax number is valid.
        
        In production, you could:
        1. Check format
        2. Use a fax validation API
        3. Send a test fax (expensive)
        """
        if not fax:
            return False
        
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', fax)
        
        # Should be 10 or 11 digits
        return len(digits) in [10, 11]


# Singleton instance
_finder = None

def get_medical_records_finder() -> MedicalRecordsFinder:
    """Get singleton instance of MedicalRecordsFinder."""
    global _finder
    if _finder is None:
        _finder = MedicalRecordsFinder()
    return _finder


def find_and_cache_medical_records_fax(
    hospital_name: str,
    city: Optional[str] = None,
    state: Optional[str] = None,
    website: Optional[str] = None
) -> Dict:
    """
    Convenience function to find medical records fax.
    
    Returns:
        Dict with fax, confidence, source, verification_url, method
    """
    finder = get_medical_records_finder()
    return finder.find_medical_records_fax(hospital_name, city, state, website)
