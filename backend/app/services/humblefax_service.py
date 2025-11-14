# backend/app/services/humblefax_service.py
"""
HumbleFax API Service

Handles all interactions with the HumbleFax API for sending and receiving faxes.
Uses HTTP Basic Authentication with API Access Key and API Secret Key.

HumbleFax API Documentation: https://api.humblefax.com/
"""

import requests
import os
import logging
import base64
import re
from typing import List, Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)

# HumbleFax credentials from environment
HUMBLEFAX_ACCESS_KEY = os.getenv("HUMBLEFAX_ACCESS_KEY")
HUMBLEFAX_SECRET_KEY = os.getenv("HUMBLEFAX_SECRET_KEY")

# Base URL for HumbleFax API
BASE_URL = "https://api.humblefax.com"


def get_auth():
    """Get HTTP Basic Auth tuple for requests"""
    if not HUMBLEFAX_ACCESS_KEY or not HUMBLEFAX_SECRET_KEY:
        logger.error("HumbleFax credentials not configured")
        return None
    return (HUMBLEFAX_ACCESS_KEY, HUMBLEFAX_SECRET_KEY)


def validate_fax_number(fax: str) -> bool:
    """Validate fax number format."""
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
    Example: "+1 555-123-4567" becomes 15551234567
    """
    # Remove all non-digits
    digits = re.sub(r'\D', '', fax)
    
    # If it's 10 digits, assume US and add 1
    if len(digits) == 10:
        digits = f"1{digits}"
    
    # Return as integer
    return int(digits)


def download_fax(fax_id: str) -> Dict:
    """
    Download a received fax from HumbleFax.
    
    Note: HumbleFax typically delivers inbound faxes via webhook with the PDF included.
    This function is for retrieving faxes if needed separately.
    
    Args:
        fax_id: The HumbleFax fax ID
        
    Returns:
        Dict with:
        - success: bool
        - file_path: str (if successful)
        - pdf_bytes: bytes (if successful)
        - error: str (if failed)
    """
    auth = get_auth()
    if not auth:
        return {
            "success": False,
            "error": "missing_credentials",
            "message": "HumbleFax credentials not configured"
        }
    
    # HumbleFax endpoint to get fax details/download
    # Note: This is an assumption - actual endpoint may differ
    url = f"{BASE_URL}/fax/{fax_id}"
    
    logger.info(f"Downloading fax: fax_id={fax_id}")
    
    try:
        r = requests.get(url, auth=auth, timeout=60)
        
        if r.status_code != 200:
            logger.error(f"Fax download failed: {r.status_code} - {r.text}")
            return {
                "success": False,
                "error": "download_failed",
                "status": r.status_code,
                "message": f"HTTP {r.status_code}: {r.text}"
            }
        
        # Check if response is PDF
        if 'application/pdf' in r.headers.get('Content-Type', ''):
            # Direct PDF response
            pdf_bytes = r.content
        else:
            # JSON response with PDF data
            data = r.json()
            if 'data' in data and 'file' in data['data']:
                # Assume base64 encoded
                pdf_bytes = base64.b64decode(data['data']['file'])
            else:
                return {
                    "success": False,
                    "error": "no_pdf_data",
                    "message": "No PDF data found in response"
                }
        
        # Save to disk
        out_dir = Path("received_faxes")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{fax_id}.pdf"
        
        with open(out_path, "wb") as f:
            f.write(pdf_bytes)
        
        logger.info(f"Fax downloaded successfully to: {out_path}")
        return {
            "success": True,
            "file_path": str(out_path),
            "pdf_bytes": pdf_bytes,
            "message": "Fax downloaded successfully"
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {e}")
        return {
            "success": False,
            "error": "request_failed",
            "message": f"HTTP request failed: {e}"
        }
    except Exception as e:
        logger.exception(f"Unexpected error downloading fax: {e}")
        return {
            "success": False,
            "error": "unexpected_error",
            "message": str(e)
        }


def send_fax(
        *,
        to_number: str,
        file_paths: List[str],
        cover_text: Optional[str] = None,
        callback_url: Optional[str] = None,
        from_name: Optional[str] = None,
        to_name: Optional[str] = None
) -> Dict:
    """
    Send a fax via HumbleFax API using the multi-step process:
    1. Create temporary fax
    2. Upload attachments
    3. Send the fax
    
    Args:
        to_number: Recipient fax number
        file_paths: List of file paths to send
        cover_text: Optional cover page message
        callback_url: Optional webhook URL for status updates
        from_name: Optional sender name for cover page
        to_name: Optional recipient name for cover page
        
    Returns:
        Dict with keys:
        - success: bool
        - tmpFaxId: str (HumbleFax temp fax ID)
        - message: str
        - error: str (if failed)
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
        logger.error(f"Invalid fax number format: {to_number}")
        return {
            "success": False,
            "error": "invalid_fax_number",
            "message": f"Invalid fax number: {to_number}"
        }
    
    formatted_fax = format_fax_number(to_number)
    logger.info(f"Sending fax to: {to_number} (formatted: {formatted_fax})")
    
    # Validate files exist
    for path in file_paths:
        if not os.path.exists(path):
            logger.error(f"File not found: {path}")
            return {
                "success": False,
                "error": "file_not_found",
                "message": f"File not found: {path}"
            }
    
    try:
        # STEP 1: Create temporary fax
        logger.info("Step 1: Creating temporary fax")
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
        
        # Optional: Add custom UUID for tracking
        # tmp_fax_payload["uuid"] = str(uuid.uuid4())
        
        r = requests.post(
            f"{BASE_URL}/tmpFax",
            json=tmp_fax_payload,
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if r.status_code != 200:
            logger.error(f"Failed to create temp fax: {r.status_code} - {r.text}")
            return {
                "success": False,
                "error": "create_tmpfax_failed",
                "status": r.status_code,
                "message": f"Failed to create temp fax: {r.text}"
            }
        
        tmp_fax_data = r.json()
        if 'data' not in tmp_fax_data or 'tmpFax' not in tmp_fax_data['data']:
            logger.error(f"Invalid tmpFax response: {tmp_fax_data}")
            return {
                "success": False,
                "error": "invalid_response",
                "message": "Invalid response from tmpFax creation"
            }
        
        tmp_fax_id = tmp_fax_data['data']['tmpFax']['id']
        logger.info(f"✅ Created temp fax: {tmp_fax_id}")
        
        # STEP 2: Upload attachments
        logger.info(f"Step 2: Uploading {len(file_paths)} attachment(s)")
        
        for file_path in file_paths:
            logger.info(f"Uploading: {file_path}")
            
            try:
                with open(file_path, 'rb') as f:
                    files = {os.path.basename(file_path): f}
                    
                    upload_r = requests.post(
                        f"{BASE_URL}/attachment/{tmp_fax_id}",
                        files=files,
                        auth=auth,
                        timeout=120  # Longer timeout for file uploads
                    )
                    
                    if upload_r.status_code != 200:
                        logger.error(f"Failed to upload {file_path}: {upload_r.status_code} - {upload_r.text}")
                        return {
                            "success": False,
                            "error": "upload_failed",
                            "message": f"Failed to upload {os.path.basename(file_path)}: {upload_r.text}"
                        }
                    
                    logger.info(f"✅ Uploaded: {os.path.basename(file_path)}")
                    
            except Exception as e:
                logger.error(f"Error uploading file {file_path}: {e}")
                return {
                    "success": False,
                    "error": "file_upload_error",
                    "message": f"Error uploading file: {e}"
                }
        
        # STEP 3: Send the fax
        logger.info("Step 3: Sending fax")
        
        send_r = requests.post(
            f"{BASE_URL}/tmpFax/{tmp_fax_id}/send",
            auth=auth,
            timeout=30
        )
        
        if send_r.status_code != 200:
            logger.error(f"Failed to send fax: {send_r.status_code} - {send_r.text}")
            return {
                "success": False,
                "error": "send_failed",
                "status": send_r.status_code,
                "message": f"Failed to send fax: {send_r.text}"
            }
        
        send_data = send_r.json()
        logger.info(f"✅ Fax queued successfully! TmpFaxID: {tmp_fax_id}")
        
        # Note: HumbleFax will send status updates to configured webhook URL in dashboard
        # or via email notifications
        
        return {
            "success": True,
            "tmpFaxId": tmp_fax_id,
            "message": f"Fax queued successfully to {to_number}",
            "response": send_data
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {e}")
        return {
            "success": False,
            "error": "request_failed",
            "message": f"HTTP request failed: {e}"
        }
    except Exception as e:
        logger.exception(f"Unexpected error sending fax: {e}")
        return {
            "success": False,
            "error": "unexpected_error",
            "message": str(e)
        }


def get_sent_fax_status(tmp_fax_id: str) -> Dict:
    """
    Get the status of a sent fax.
    
    Note: HumbleFax primarily uses webhooks for status updates.
    This is a polling fallback if webhooks aren't configured.
    
    Args:
        tmp_fax_id: The HumbleFax temporary fax ID
        
    Returns:
        Dict with fax status information
    """
    auth = get_auth()
    if not auth:
        return {
            "success": False,
            "error": "missing_credentials",
            "message": "HumbleFax credentials not configured"
        }
    
    try:
        # Try to get sent fax details
        # Note: Actual endpoint may vary - adjust based on HumbleFax documentation
        url = f"{BASE_URL}/sentFax/{tmp_fax_id}"
        
        r = requests.get(url, auth=auth, timeout=30)
        
        if r.status_code != 200:
            logger.error(f"Failed to get fax status: {r.status_code} - {r.text}")
            return {
                "success": False,
                "error": "status_check_failed",
                "message": f"Failed to get fax status: {r.text}"
            }
        
        data = r.json()
        logger.info(f"Fax status retrieved: {tmp_fax_id}")
        
        return {
            "success": True,
            "status": data,
            "message": "Status retrieved successfully"
        }
        
    except Exception as e:
        logger.exception(f"Error getting fax status: {e}")
        return {
            "success": False,
            "error": "unexpected_error",
            "message": str(e)
        }
