# Veritas One — Medical Records Fax Collector

This application helps patients collect their medical records from all facilities they have ever been to by automating the faxing and retrieval process.

## Overview

Currently, health records are often scanned and faxed. This application automates fetching and retrieving faxed healthcare data and integrates it into searchable text documents for patients.

## Features

- **Patient Registration**: Simple registration form with consent signature
- **Automated Provider Search**: Search for healthcare providers by city or ZIP code using the NPPES directory
- **Digital Faxing**: Automatically sends HIPAA-compliant release forms to providers via iFax
- **Incoming Fax Processing**: Receives and processes incoming faxes with OCR
- **Patient Matching**: Uses OCR to extract patient name and DOB to match faxes to patients
- **PDF Compilation**: Aggregates all received records into a single searchable PDF
- **Patient Portal**: Secure portal where patients can download their compiled records

## Workflow

1. **Landing Page**: Explains how the app works
2. **Registration**: Patient registers and provides basic information
3. **Consent**: Patient signs a digital consent form for medical records release
4. **Provider Selection**: Patient specifies cities, ZIP codes, or specific providers
5. **Automated Faxing**: System searches for providers and sends fax requests
6. **Fax Reception**: Incoming faxes are received via iFax webhook
7. **OCR Processing**: Each fax is OCR'd and patient information is extracted
8. **Patient Matching**: Faxes are matched to patients by name and DOB
9. **PDF Compilation**: Once all responses are received, records are compiled into one searchable PDF
10. **Portal Access**: Patient can download their compiled records from their portal

## Quick Start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # set IFAX_ACCESS_TOKEN and DATABASE_URL
./scripts/dev-start.sh  # On Windows: scripts\dev-start.ps1
```

Open http://localhost:8000/ in your browser.

## Configuration

Create a `.env` file in the `backend` directory:

```
DATABASE_URL=sqlite+aiosqlite:///./dev.db
# For production, use PostgreSQL:
# DATABASE_URL=postgresql+asyncpg://user:password@host:5432/database

IFAX_ACCESS_TOKEN=your_ifax_token_here
BASE_EXTERNAL_URL=https://your-domain.com
```

## Database

The application uses SQLAlchemy with async support and can work with:
- **SQLite** (default, for development)
- **PostgreSQL** (recommended for production)

Tables are automatically created on startup.

## iFax Integration

You need an iFax account and API token. Configure webhook URLs in your iFax dashboard:
- **Inbound fax webhook**: `https://your-domain.com/ifax/receive`
- **Outbound status webhook**: `https://your-domain.com/ifax/outbound-status`

## API Endpoints

- `GET /` - Landing page
- `GET /register` - Registration form
- `POST /register` - Submit registration
- `GET /consent/{patient_id}` - Consent form
- `POST /consent/{patient_id}` - Submit consent with signature
- `GET /providers/{patient_id}` - Provider search form
- `POST /providers/{patient_id}` - Submit provider search
- `GET /status/{request_id}` - View request status
- `GET /portal/{patient_uuid}` - Patient portal
- `GET /portal/{patient_uuid}/download/{request_id}` - Download compiled PDF
- `POST /ifax/receive` - iFax webhook for incoming faxes
- `POST /ifax/outbound-status` - iFax webhook for outbound status

## Storage

Files are stored in the `storage/` directory:
- `storage/signatures/` - Patient signature images
- `storage/releases/` - Consent PDFs
- `storage/covers/` - Fax cover sheets
- `storage/` - Compiled patient record PDFs
- `received_faxes/` - Incoming fax files

## OCR Requirements

For OCR functionality, you need:
- **Tesseract OCR**: Install via `apt-get install tesseract-ocr` (Linux) or `brew install tesseract` (Mac)
- **Poppler**: Install via `apt-get install poppler-utils` (Linux) or `brew install poppler` (Mac)
- **ocrmypdf** (optional): For creating searchable PDFs: `pip install ocrmypdf`

## Production Deployment

1. Use PostgreSQL for the database
2. Set up proper SSL/TLS
3. Configure iFax webhooks with your production URL
4. Use environment variables for all secrets
5. Set up proper logging and monitoring
6. Consider using a reverse proxy (nginx/caddy)
7. Use a process manager (systemd/supervisor)

## Security Notes

- All patient data is stored securely in the database
- Signatures are captured as PNG images
- Consent forms are generated as PDFs with patient information
- Patient portals use UUID-based URLs for security
- All fax transmissions use iFax's secure infrastructure

## License

© 2025 Veritas One
