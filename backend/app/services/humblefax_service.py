# backend/app/services/humblefax_service.py
"""
HumbleFax API Service - Complete Implementation

Handles all interactions with the HumbleFax API for sending and receiving faxes.
Uses HTTP Basic Authentication with API Access Key and API Secret Key.

HumbleFax API Documentation: https://api.humblefax.com/

Key Functions:
- get_incoming_faxes(): List incoming faxes with date filters
- download_incoming_fax(): Download a specific fax PDF
- send_fax(): Send outbound faxes with attachments
"""

import requests
import os
import logging
import base64
import re
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# HumbleFax credentials from environment
HUMBLEFAX_ACCESS_KEY = os.getenv("HUMBLEFAX_ACCESS_KEY")
HUMBLEFAX_SECRET_KEY = os.getenv("HUMBLEFAX_SECRET_KEY")

# Base URL for HumbleFax API
BASE_URL = "https://api.humblefax.com"

# Timeouts (seconds)
DOWNLOAD_TIMEOUT = 60
UPLOAD_TIMEOUT = 120
LIST_TIMEOUT = 30


def get_auth() -> Optional[tuple]:
    """
    Get HTTP Basic Auth tuple for requests.

    Returns:
        Tuple of (username, password) or None if not configured
    """
    if not HUMBLEFAX_ACCESS_KEY or not HUMBLEFAX_SECRET_KEY:
        logger.error("❌ HumbleFax credentials not configured in environment")
        return None
    return (HUMBLEFAX_ACCESS_KEY, HUMBLEFAX_SECRET_KEY)


# ============================================================================
# INCOMING FAX FUNCTIONS
# ============================================================================

def get_incoming_faxes(
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100
) -> List[Dict]:
    """
    Retrieve list of incoming faxes from HumbleFax API.

    Endpoint: GET /incomingFaxes

    Args:
        since: Start datetime (defaults to 24 hours ago)
        until: End datetime (defaults to now)
        limit: Maximum number of results (default 100)

    Returns:
        List of fax dictionaries with keys:
        - id: Fax ID
        - from: Sender number
        - to: Receiver number
        - pages: Number of pages
        - receivedAt: ISO timestamp
        - status: Fax status

    Example:
        faxes = get_incoming_faxes(since=datetime.now() - timedelta(hours=24))
    """
    auth = get_auth()
    if not auth:
        logger.error("Cannot fetch incoming faxes - missing credentials")
        return []

    # Set defaults
    if since is None:
        since = datetime.utcnow() - timedelta(hours=24)
    if until is None:
        until = datetime.utcnow()

    # Format dates for API (ISO 8601 with Z suffix)
    start_date = since.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    end_date = until.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    url = f"{BASE_URL}/incomingFaxes"
    params = {
        "startDate": start_date,
        "endDate": end_date,
        "limit": limit
    }

    logger.info(f"🔍 Fetching incoming faxes: {start_date} to {end_date}")

    try:
        response = requests.get(
            url,
            auth=auth,
            params=params,
            timeout=LIST_TIMEOUT
        )

        if response.status_code != 200:
            logger.error(
                f"❌ Failed to fetch incoming faxes: "
                f"{response.status_code} - {response.text}"
            )
            return []

        data = response.json()

        # Parse response structure
        # HumbleFax likely returns: {"data": {"incomingFaxes": [...]}}
        if isinstance(data, dict):
            # Try nested structure first
            faxes = data.get('data', {}).get('incomingFaxes', [])
            if not faxes:
                # Try flat structure
                faxes = data.get('incomingFaxes', [])
            if not faxes and 'data' in data:
                # Maybe data is the array itself
                faxes = data['data'] if isinstance(data['data'], list) else []
        elif isinstance(data, list):
            # Direct array response
            faxes = data
        else:
            logger.error(f"Unexpected response format: {type(data)}")
            faxes = []

        logger.info(f"✅ Retrieved {len(faxes)} incoming faxes")

        # Log sample for debugging (first fax only)
        if faxes and len(faxes) > 0:
            logger.debug(f"Sample fax structure: {faxes[0]}")

        return faxes

    except requests.exceptions.Timeout:
        logger.error(f"⏱️ Request timeout while fetching incoming faxes")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Request failed: {e}")
        return []
    except Exception as e:
        logger.exception(f"❌ Unexpected error fetching incoming faxes: {e}")
        return []


def download_incoming_fax(fax_id: str, save_to_disk: bool = True) -> Dict:
    """
    Download a specific incoming fax PDF from HumbleFax.

    Endpoint: GET /incomingFax/{id}/download

    This is used when:
    1. The webhook doesn't include the PDF data
    2. You need to retrieve an older fax
    3. Polling for missed faxes

    Args:
        fax_id: The HumbleFax fax ID
        save_to_disk: Whether to save PDF to disk (default True)

    Returns:
        Dict with keys:
        - success: bool - Whether download succeeded
        - file_path: str - Path to saved file (if save_to_disk=True)
        - pdf_bytes: bytes - Raw PDF data
        - error: str - Error code if failed
        - message: str - Human-readable message

    Example:
        result = download_incoming_fax("fax_abc123")
        if result["success"]:
            pdf_data = result["pdf_bytes"]
            file_path = result["file_path"]
    """
    auth = get_auth()
    if not auth:
        return {
            "success": False,
            "error": "missing_credentials",
            "message": "HumbleFax credentials not configured"
        }

    # Download endpoint for incoming fax
    url = f"{BASE_URL}/incomingFax/{fax_id}/download"

    logger.info(f"📥 Downloading incoming fax: {fax_id}")

    try:
        response = requests.get(url, auth=auth, timeout=DOWNLOAD_TIMEOUT)

        if response.status_code != 200:
            logger.error(
                f"❌ Download failed: {response.status_code} - {response.text}"
            )
            return {
                "success": False,
                "error": "download_failed",
                "status": response.status_code,
                "message": f"HTTP {response.status_code}: {response.text[:200]}"
            }

        # Response should be PDF binary data
        pdf_bytes = response.content

        # Validate PDF data
        if not pdf_bytes or len(pdf_bytes) < 100:
            logger.error("❌ Downloaded data is too small to be a valid PDF")
            return {
                "success": False,
                "error": "invalid_pdf",
                "message": f"Downloaded data is only {len(pdf_bytes)} bytes"
            }

        # Check if it's actually a PDF (starts with %PDF)
        if not pdf_bytes.startswith(b'%PDF'):
            logger.warning(
                "⚠️ Downloaded data doesn't start with PDF signature"
            )
            # Don't fail - some PDFs might be wrapped differently

        result = {
            "success": True,
            "pdf_bytes": pdf_bytes,
            "message": f"Downloaded {len(pdf_bytes)} bytes"
        }

        # Save to disk if requested
        if save_to_disk:
            try:
                out_dir = Path("received_faxes")
                out_dir.mkdir(exist_ok=True)
                out_path = out_dir / f"{fax_id}.pdf"

                with open(out_path, "wb") as f:
                    f.write(pdf_bytes)

                result["file_path"] = str(out_path)
                logger.info(f"✅ Saved to: {out_path}")

            except Exception as e:
                logger.error(f"⚠️ Failed to save to disk: {e}")
                # Don't fail the whole operation
                result["file_save_error"] = str(e)

        return result

    except requests.exceptions.Timeout:
        logger.error(f"⏱️ Download timeout for fax {fax_id}")
        return {
            "success": False,
            "error": "timeout",
            "message": f"Download timed out after {DOWNLOAD_TIMEOUT}s"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Request failed: {e}")
        return {
            "success": False,
            "error": "request_failed",
            "message": f"HTTP request failed: {str(e)}"
        }
    except Exception as e:
        logger.exception(f"❌ Unexpected error downloading fax: {e}")
        return {
            "success": False,
            "error": "unexpected_error",
            "message": str(e)
        }


# ============================================================================
# OUTBOUND FAX FUNCTIONS
# ============================================================================

def validate_fax_number(fax: str) -> bool:
    """
    Validate fax number format.

    Args:
        fax: Fax number string

    Returns:
        True if valid, False otherwise
    """
    if not fax:
        return False
    # Remove all non-digits
    digits = re.sub(r'\D', '', fax)
    # Should be 10-15 digits
    return 10 <= len(digits) <= 15


def format_fax_number(fax: str) -> int:
    """
    Format fax number for HumbleFax API.

    HumbleFax expects fax numbers as integers (no formatting).

    Args:
        fax: Fax number in any format (e.g., "+1 555-123-4567")

    Returns:
        Integer fax number (e.g., 15551234567)

    Example:
        format_fax_number("+1 (555) 123-4567")  # Returns: 15551234567
    """
    # Remove all non-digits
    digits = re.sub(r'\D', '', fax)

    # If it's 10 digits, assume US and add country code 1
    if len(digits) == 10:
        digits = f"1{digits}"

    return int(digits)


def send_fax(
        *,
        to_number: str,
        file_paths: List[str],
        cover_text: Optional[str] = None,
        from_name: Optional[str] = None,
        to_name: Optional[str] = None,
        callback_url: Optional[str] = None
) -> Dict:
    """
    Send a fax via HumbleFax API using the multi-step process:
    1. Create temporary fax
    2. Upload attachments
    3. Send the fax

    Args:
        to_number: Recipient fax number (e.g., "+1 555-123-4567")
        file_paths: List of file paths to send (PDFs, DOCs, etc.)
        cover_text: Optional cover page message
        from_name: Optional sender name for cover page
        to_name: Optional recipient name for cover page
        callback_url: Optional webhook URL for status updates

    Returns:
        Dict with keys:
        - success: bool - Whether fax was sent successfully
        - tmpFaxId: str - HumbleFax temporary fax ID
        - message: str - Human-readable message
        - error: str - Error code if failed (optional)

    Example:
        result = send_fax(
            to_number="+15551234567",
            file_paths=["release.pdf"],
            cover_text="Medical records request",
            from_name="Health Records Portal"
        )
    """
    auth = get_auth()
    if not auth:
        return {
            "success": False,
            "error": "missing_credentials",
            "message": "HumbleFax API credentials not configured"
        }

    # Validate and format fax number
    if not validate_fax_number(to_number):
        logger.error(f"❌ Invalid fax number format: {to_number}")
        return {
            "success": False,
            "error": "invalid_fax_number",
            "message": f"Invalid fax number: {to_number}"
        }

    formatted_fax = format_fax_number(to_number)
    logger.info(f"📤 Sending fax to: {to_number} (formatted: {formatted_fax})")

    # Validate files exist
    for path in file_paths:
        if not os.path.exists(path):
            logger.error(f"❌ File not found: {path}")
            return {
                "success": False,
                "error": "file_not_found",
                "message": f"File not found: {path}"
            }

    try:
        # ===================================================================
        # STEP 1: Create temporary fax
        # ===================================================================
        logger.info("📋 Step 1: Creating temporary fax")

        tmp_fax_payload = {
            "recipients": [formatted_fax],
            "resolution": "Fine",
            "pageSize": "Letter",
            "includeCoversheet": bool(cover_text)
        }

        # Add cover page details if provided
        if cover_text:
            tmp_fax_payload["message"] = cover_text
        if from_name:
            tmp_fax_payload["fromName"] = from_name
        if to_name:
            tmp_fax_payload["toName"] = to_name

        response = requests.post(
            f"{BASE_URL}/tmpFax",
            json=tmp_fax_payload,
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code != 200:
            logger.error(
                f"❌ Failed to create temp fax: "
                f"{response.status_code} - {response.text}"
            )
            return {
                "success": False,
                "error": "create_tmpfax_failed",
                "status": response.status_code,
                "message": f"Failed to create temp fax: {response.text[:200]}"
            }

        tmp_fax_data = response.json()

        # Extract tmpFax ID from response
        if 'data' not in tmp_fax_data or 'tmpFax' not in tmp_fax_data['data']:
            logger.error(f"❌ Invalid tmpFax response: {tmp_fax_data}")
            return {
                "success": False,
                "error": "invalid_response",
                "message": "Invalid response from tmpFax creation"
            }

        tmp_fax_id = tmp_fax_data['data']['tmpFax']['id']
        logger.info(f"✅ Created temp fax: {tmp_fax_id}")

        # ===================================================================
        # STEP 2: Upload attachments
        # ===================================================================
        logger.info(f"📎 Step 2: Uploading {len(file_paths)} attachment(s)")

        for file_path in file_paths:
            file_name = os.path.basename(file_path)
            logger.info(f"  Uploading: {file_name}")

            try:
                with open(file_path, 'rb') as f:
                    files = {file_name: f}

                    upload_response = requests.post(
                        f"{BASE_URL}/attachment/{tmp_fax_id}",
                        files=files,
                        auth=auth,
                        timeout=UPLOAD_TIMEOUT
                    )

                    if upload_response.status_code != 200:
                        logger.error(
                            f"❌ Failed to upload {file_name}: "
                            f"{upload_response.status_code} - {upload_response.text}"
                        )
                        return {
                            "success": False,
                            "error": "upload_failed",
                            "tmpFaxId": tmp_fax_id,
                            "message": f"Failed to upload {file_name}"
                        }

                    logger.info(f"  ✅ Uploaded: {file_name}")

            except Exception as e:
                logger.exception(f"❌ Error uploading {file_name}: {e}")
                return {
                    "success": False,
                    "error": "upload_exception",
                    "tmpFaxId": tmp_fax_id,
                    "message": f"Error uploading {file_name}: {str(e)}"
                }

        # ===================================================================
        # STEP 3: Send the fax
        # ===================================================================
        logger.info("📨 Step 3: Sending fax")

        send_response = requests.post(
            f"{BASE_URL}/tmpFax/{tmp_fax_id}/send",
            auth=auth,
            timeout=30
        )

        if send_response.status_code != 200:
            logger.error(
                f"❌ Failed to send fax: "
                f"{send_response.status_code} - {send_response.text}"
            )
            return {
                "success": False,
                "error": "send_failed",
                "tmpFaxId": tmp_fax_id,
                "status": send_response.status_code,
                "message": f"Failed to send fax: {send_response.text[:200]}"
            }

        logger.info(f"✅ Fax sent successfully: {tmp_fax_id}")

        return {
            "success": True,
            "tmpFaxId": tmp_fax_id,
            "message": f"Fax sent to {to_number}",
            "recipient": to_number
        }

    except requests.exceptions.Timeout as e:
        logger.error(f"⏱️ Timeout during fax send: {e}")
        return {
            "success": False,
            "error": "timeout",
            "message": f"Request timed out: {str(e)}"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Request error during fax send: {e}")
        return {
            "success": False,
            "error": "request_failed",
            "message": f"HTTP request failed: {str(e)}"
        }
    except Exception as e:
        logger.exception(f"❌ Unexpected error sending fax: {e}")
        return {
            "success": False,
            "error": "unexpected_error",
            "message": str(e)
        }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def test_credentials() -> Dict:
    """
    Test HumbleFax API credentials by making a simple API call.

    Returns:
        Dict with:
        - valid: bool
        - message: str
    """
    auth = get_auth()
    if not auth:
        return {
            "valid": False,
            "message": "Credentials not configured"
        }

    try:
        # Try to list incoming faxes as a credential test
        response = requests.get(
            f"{BASE_URL}/incomingFaxes",
            auth=auth,
            params={"limit": 1},
            timeout=10
        )

        if response.status_code == 401:
            return {
                "valid": False,
                "message": "Invalid credentials (401 Unauthorized)"
            }
        elif response.status_code == 200:
            return {
                "valid": True,
                "message": "Credentials valid"
            }
        else:
            return {
                "valid": False,
                "message": f"Unexpected response: {response.status_code}"
            }

    except Exception as e:
        return {
            "valid": False,
            "message": f"Error testing credentials: {str(e)}"
        }