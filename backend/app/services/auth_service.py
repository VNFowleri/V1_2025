# backend/app/services/auth_service.py

import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# In-memory storage for magic links (in production, use Redis or database)
magic_links = {}

def generate_magic_link(email: str, base_url: str) -> str:
    """Generate a magic link for passwordless login."""
    # Generate secure token
    token = secrets.token_urlsafe(32)
    
    # Hash the token for storage
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Store with expiration (15 minutes)
    expiration = datetime.utcnow() + timedelta(minutes=15)
    magic_links[token_hash] = {
        "email": email,
        "expires": expiration,
        "used": False
    }
    
    # Return the magic link
    return f"{base_url}/auth/verify?token={token}"

def verify_magic_link(token: str) -> Optional[str]:
    """Verify a magic link token and return the email if valid."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    link_data = magic_links.get(token_hash)
    if not link_data:
        logger.warning(f"Invalid token attempted: {token_hash[:10]}...")
        return None
    
    # Check if expired
    if datetime.utcnow() > link_data["expires"]:
        logger.warning(f"Expired token used: {token_hash[:10]}...")
        del magic_links[token_hash]
        return None
    
    # Check if already used
    if link_data["used"]:
        logger.warning(f"Already used token: {token_hash[:10]}...")
        return None
    
    # Mark as used
    link_data["used"] = True
    
    return link_data["email"]

def cleanup_expired_links():
    """Remove expired magic links."""
    now = datetime.utcnow()
    expired = [k for k, v in magic_links.items() if now > v["expires"]]
    for k in expired:
        del magic_links[k]
    return len(expired)

def send_magic_link_email(email: str, magic_link: str) -> bool:
    """
    Send magic link via email. In production, use SendGrid, AWS SES, etc.
    For now, just log it for development.
    """
    logger.info(f"Magic link for {email}: {magic_link}")
    
    # TODO: In production, send actual email
    # Example with SendGrid:
    # import sendgrid
    # sg = sendgrid.SendGridAPIClient(api_key=os.environ.get('SENDGRID_API_KEY'))
    # data = {
    #     "personalizations": [{"to": [{"email": email}]}],
    #     "from": {"email": "noreply@veritasone.com"},
    #     "subject": "Your Veritas One Login Link",
    #     "content": [{
    #         "type": "text/html",
    #         "value": f'<p>Click here to log in: <a href="{magic_link}">Access Your Portal</a></p>'
    #     }]
    # }
    # response = sg.client.mail.send.post(request_body=data)
    
    print(f"\n{'='*60}")
    print(f"MAGIC LINK FOR: {email}")
    print(f"Link: {magic_link}")
    print(f"{'='*60}\n")
    
    return True
