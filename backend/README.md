# Veritas One — Medical Records Fax Collector (Portal download)

This build removes all email-sending and instead exposes a **patient portal** with a magic-link where patients can download the compiled, searchable PDF once ready.

## Flow
- Landing → Register → E-sign HIPAA release → Add cities/ZIPs/providers
- Backend sends faxes via **iFax**
- Inbound faxes land via **iFax** webhook → OCR → match to patient
- When providers respond (or fail), backend compiles all PDFs into one searchable PDF,
  records the file path on the `RecordRequest`, and marks it complete.
- Patient visits **/portal/{patient_uuid}** to download the compiled PDF (no email).

## Quick Start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # set IFAX_ACCESS_TOKEN
uvicorn app.main:app --reload --port 8000
```
