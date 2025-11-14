# backend/app/services/ifax_service.py - IMPROVED WITH DEBUGGING

import requests
import os
import logging
import base64
import re
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)
IFAX_ACCESS_TOKEN = os.getenv("IFAX_ACCESS_TOKEN")

BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "accessToken": IFAX_ACCESS_TOKEN or ""
}


def validate_fax_number(fax: str) -> bool:
    """Validate fax number format."""
    if not fax:
        return False
    # Remove all non-digits
    digits = re.sub(r'\D', '', fax)
    # Should be 10-15 digits
    return 10 <= len(digits) <= 15


def format_fax_e164(fax: str) -> str:
    """Format fax number to E.164 format (+1234567890)."""
    # Remove all non-digits
    digits = re.sub(r'\D', '', fax)

    # If it's 10 digits, assume US and add +1
    if len(digits) == 10:
        return f"+1{digits}"

    # If it's 11 digits and starts with 1, add +
    if len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"

    # Otherwise, just add + if not there
    if not fax.startswith('+'):
        return f"+{digits}"

    return fax


def download_fax(job_id: str, transaction_id: int):
    """Download a received fax from iFax."""
    url = "https://api.ifaxapp.com/v1/customer/inbound/fax-download"
    payload = {"jobId": str(job_id), "transactionId": str(transaction_id)}

    logger.info(f"Downloading fax: jobId={job_id}, transactionId={transaction_id}")

    r = requests.post(url, json=payload, headers=BASE_HEADERS, timeout=60)

    if r.status_code != 200:
        logger.error(f"Fax download failed: {r.status_code} - {r.text}")
        return {"error": "Failed to download fax", "status": r.status_code, "body": r.text}

    data = r.json()

    if data.get("status") != 1:
        logger.error(f"Fax download failed: {data}")
        return {"error": "Fax download failed", "body": data}

    file_b64 = data.get("data")
    if not file_b64:
        return {"error": "No file data in response"}

    pdf_bytes = base64.b64decode(file_b64)
    out_dir = os.path.join(os.getcwd(), "received_faxes")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{job_id}.pdf")

    with open(out_path, "wb") as f:
        f.write(pdf_bytes)

    logger.info(f"Fax downloaded successfully to: {out_path}")
    return {"message": "Fax downloaded", "file_path": out_path}


def send_fax(
        *,
        to_number: str,
        file_paths: List[str],
        cover_text: Optional[str] = None,
        callback_url: Optional[str] = None
) -> Dict:
    """
    Send a fax via iFax API.

    Returns:
        Dict with keys:
        - success: bool
        - jobId: str (if successful)
        - message: str
        - error: str (if failed)
        - response: dict (full API response)
    """
    url = "https://api.ifaxapp.com/v1/customer/fax-send"

    # Validate and format fax number
    if not validate_fax_number(to_number):
        logger.error(f"Invalid fax number format: {to_number}")
        return {
            "success": False,
            "error": "invalid_fax_number",
            "message": f"Invalid fax number: {to_number}"
        }

    formatted_fax = format_fax_e164(to_number)
    logger.info(f"Sending fax to: {to_number} (formatted: {formatted_fax})")

    # Prepare files
    files_payload = []
    for p in file_paths:
        if not os.path.exists(p):
            logger.error(f"File not found: {p}")
            return {
                "success": False,
                "error": "file_not_found",
                "message": f"File not found: {p}"
            }

        try:
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
                files_payload.append({
                    "name": os.path.basename(p),
                    "data": b64
                })
                logger.info(f"Added file to fax: {os.path.basename(p)} ({len(b64)} chars)")
        except Exception as e:
            logger.error(f"Error reading file {p}: {e}")
            return {
                "success": False,
                "error": "file_read_error",
                "message": f"Error reading file: {e}"
            }

    # Prepare payload - iFax expects faxNumber at top level
    payload = {
        "faxNumber": formatted_fax,  # Changed from recipient.faxNumber
        "files": files_payload,
        "coverPage": {"text": cover_text or "Medical Records Request"},
    }

    if callback_url:
        payload["webhook"] = {"statusUrl": callback_url}
        logger.info(f"Webhook configured: {callback_url}")

    # Log request (without file data)
    log_payload = payload.copy()
    log_payload["files"] = [{"name": f["name"], "size": len(f["data"])} for f in payload["files"]]
    logger.info(f"Sending fax request: {log_payload}")

    # Check if API token is set
    if not IFAX_ACCESS_TOKEN:
        logger.error("IFAX_ACCESS_TOKEN not set!")
        return {
            "success": False,
            "error": "missing_api_token",
            "message": "iFax API token not configured"
        }

    # Send request
    try:
        r = requests.post(url, json=payload, headers=BASE_HEADERS, timeout=60)
        logger.info(f"iFax API response: {r.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {e}")
        return {
            "success": False,
            "error": "request_failed",
            "message": f"HTTP request failed: {e}"
        }

    # Check HTTP status
    if r.status_code != 200:
        logger.error(f"Fax send failed: {r.status_code} - {r.text}")
        return {
            "success": False,
            "error": "http_error",
            "status": r.status_code,
            "message": f"HTTP {r.status_code}: {r.text}",
            "body": r.text
        }

    # Parse response
    try:
        data = r.json()
        logger.info(f"iFax API response data: {data}")
    except Exception as e:
        logger.error(f"Invalid JSON response: {r.text}")
        return {
            "success": False,
            "error": "invalid_json",
            "message": "Invalid JSON response from API",
            "body": r.text
        }

    # Check if fax was actually queued
    # iFax API returns {"status": 1, "jobId": "12345", ...} on success
    # or {"status": 0, "message": "error"} on failure
    status = data.get("status")
    job_id = data.get("jobId") or data.get("data", {}).get("jobId")

    if status == 1 and job_id:
        logger.info(f"✅ Fax queued successfully! JobID: {job_id}")
        return {
            "success": True,
            "jobId": str(job_id),
            "message": f"Fax queued successfully to {formatted_fax}",
            "response": data
        }
    else:
        error_message = data.get("message", "Unknown error")
        logger.error(f"❌ Fax send failed: {error_message}")
        logger.error(f"Full response: {data}")
        return {
            "success": False,
            "error": "api_error",
            "message": error_message,
            "response": data
        }