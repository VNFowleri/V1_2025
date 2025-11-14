# Quick Start Guide

## Fix Applied ✅

The error `null value in column "consent_pdf_path"` has been fixed. The application now properly captures signatures and generates consent PDFs.

## Get Running in 5 Minutes

### 1. Install System Dependencies

**macOS:**
```bash
brew install tesseract poppler
```

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr poppler-utils
```

### 2. Setup Application

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env if you have an IFAX_ACCESS_TOKEN
```

### 3. Run

```bash
# Using the startup script
./scripts/dev-start.sh

# Or manually
uvicorn app.main:app --reload --port 8000
```

### 4. Test

Open http://localhost:8000/ in your browser and:

1. Click "Get started"
2. Fill registration form
3. Sign the consent (draw on canvas)
4. Enter cities or ZIP codes
5. View status page
6. Access patient portal

## What Was Fixed

The `web.py` router's `consent_submit` function now:
- ✅ Captures signature from the form
- ✅ Saves signature as PNG
- ✅ Generates consent PDF
- ✅ Stores both paths in database

## File Structure

```
backend/
├── app/
│   ├── database/          # Database config
│   ├── models/            # SQLAlchemy models
│   ├── routers/           # API routes (FIXED: web.py)
│   ├── services/          # Business logic
│   ├── utils/             # OCR utilities
│   ├── static/            # CSS files
│   ├── templates/         # HTML templates
│   └── main.py            # FastAPI app
├── scripts/
│   └── dev-start.sh       # Startup script
├── requirements.txt       # Dependencies
├── .env.example           # Config template
└── README.md              # Full docs
```

## Next Steps

1. **Get iFax Account**: Sign up at ifaxapp.com for API access
2. **Add Token**: Put your token in `.env` file
3. **Configure Webhooks**: Set up iFax webhooks to point to your server
4. **Deploy**: Follow production deployment guide in README.md

## Quick Test Without iFax

You can test the app without iFax:
- Registration works ✅
- Consent signing works ✅
- Provider search works ✅
- Status page works ✅
- Portal works ✅

Only actual faxing requires iFax.

## Need Help?

See `SOLUTION_SUMMARY.md` for:
- Detailed explanation of the fix
- Complete workflow documentation
- Troubleshooting guide
- Production deployment tips

## Files Included

All files in `/mnt/user-data/outputs/backend/` are ready to use:
- All models with correct schema
- Fixed routers with signature handling
- Complete services (iFax, PDF, OCR)
- All HTML templates
- CSS styling
- Configuration files
- Documentation
