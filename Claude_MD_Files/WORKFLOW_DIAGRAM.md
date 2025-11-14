# Veritas One - Application Workflow

## User Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         LANDING PAGE                            │
│                      http://localhost:8000/                     │
│                                                                 │
│  "Collect all your medical records—automatically"              │
│                     [Get started]                               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      REGISTRATION FORM                          │
│                       /register (GET)                           │
│                                                                 │
│  First Name:    [________________]                              │
│  Last Name:     [________________]                              │
│  Email:         [________________]                              │
│  Phone:         [________________]                              │
│  Date of Birth: [________________]                              │
│                     [Continue]                                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ POST /register
                             │ Creates Patient record
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        CONSENT FORM                             │
│                  /consent/{patient_id} (GET)                    │
│                                                                 │
│  Authorization to Release Medical Records                       │
│  ─────────────────────────────────────────                      │
│  I authorize the release of my complete medical record...       │
│                                                                 │
│  Please sign below:                                             │
│  ┌──────────────────────────────────────┐                       │
│  │                                      │ (Canvas)              │
│  │        [Signature Area]              │                       │
│  │                                      │                       │
│  └──────────────────────────────────────┘                       │
│  [Clear]              [I agree and sign]                        │
└────────────────────────────┬────────────────────────────────────┘
                             │ POST /consent/{patient_id}
                             │ - Saves signature PNG
                             │ - Generates consent PDF
                             │ - Creates PatientConsent record
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PROVIDER SEARCH FORM                         │
│                 /providers/{patient_id} (GET)                   │
│                                                                 │
│  Where have you received care?                                 │
│                                                                 │
│  Cities:        [Austin, Seattle]                               │
│  ZIP Codes:     [94103, 78701]                                  │
│  Manual:        [{"name":"Dr Smith","fax":"+1555..."}]          │
│                                                                 │
│                    [Start requests]                             │
└────────────────────────────┬────────────────────────────────────┘
                             │ POST /providers/{patient_id}
                             │ - Searches NPPES directory
                             │ - Creates RecordRequest
                             │ - Sends faxes to providers
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       STATUS PAGE                               │
│                  /status/{request_id} (GET)                     │
│                                                                 │
│  Request ID: 123                                                │
│  Status: in_progress                                            │
│  Portal: /portal/uuid-here                                      │
│                                                                 │
│  Provider         Fax           Status      Sent      Response │
│  ─────────────────────────────────────────────────────────────  │
│  City Hospital    +1555...      fax_sent    12:00     -        │
│  Dr. Smith        +1555...      delivered   12:01     -        │
│  Main Clinic      +1555...      received    12:02     12:15    │
└─────────────────────────────────────────────────────────────────┘
                             │
                             │ Patient clicks portal link
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        PATIENT PORTAL                           │
│                  /portal/{patient_uuid} (GET)                   │
│                                                                 │
│  Your records portal                                            │
│  Patient: John Doe (DOB: 1980-01-01)                            │
│                                                                 │
│  Compiled packages:                                             │
│  ┌────────┬──────────────┬──────────────┬──────────┐            │
│  │ Req ID │ Status       │ Compiled PDF │ Complete │            │
│  ├────────┼──────────────┼──────────────┼──────────┤            │
│  │ 123    │ complete     │ [Download]   │ 12:30    │            │
│  └────────┴──────────────┴──────────────┴──────────┘            │
│                                                                 │
│  Individual faxes received:                                     │
│  ┌────┬────────────────┬───────────┬──────┐                     │
│  │ ID │ From           │ Received  │ PDF  │                     │
│  ├────┼────────────────┼───────────┼──────┤                     │
│  │ 45 │ +15551234567   │ 12:15     │ Open │                     │
│  │ 46 │ +15559876543   │ 12:18     │ Open │                     │
│  └────┴────────────────┴───────────┴──────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

## Backend Processing Flow

```
                    ┌─────────────────────────┐
                    │  Provider Search        │
                    │  (NPPES API)            │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │  Generate Cover Sheets  │
                    │  + Attach Consent PDF   │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │  Send Faxes via iFax    │
                    │  (Multiple providers)   │
                    └───────────┬─────────────┘
                                │
                                ▼
         ┌──────────────────────┴──────────────────────┐
         │                                              │
         ▼                                              ▼
┌─────────────────┐                          ┌──────────────────┐
│ Outbound Status │                          │  Inbound Faxes   │
│   Webhooks      │                          │    Webhooks      │
│   (iFax)        │                          │    (iFax)        │
└────────┬────────┘                          └────────┬─────────┘
         │                                            │
         ▼                                            ▼
┌─────────────────┐                          ┌──────────────────┐
│ Update Provider │                          │ Download Fax PDF │
│ Request Status  │                          │                  │
│ (sent/delivered)│                          └────────┬─────────┘
└─────────────────┘                                   │
                                                      ▼
                                            ┌──────────────────┐
                                            │  Run OCR on PDF  │
                                            │  Extract Text    │
                                            └────────┬─────────┘
                                                     │
                                                     ▼
                                            ┌──────────────────┐
                                            │  Parse Name/DOB  │
                                            │  Match Patient   │
                                            └────────┬─────────┘
                                                     │
                                                     ▼
                                            ┌──────────────────┐
                                            │ Link Fax to      │
                                            │ Patient & Req    │
                                            └────────┬─────────┘
                                                     │
                                                     ▼
                                            ┌──────────────────┐
                                            │ Check if all     │
                                            │ responses in     │
                                            └────────┬─────────┘
                                                     │
                                              Yes    │
                                                     ▼
                                            ┌──────────────────┐
                                            │ Convert to       │
                                            │ Searchable PDF   │
                                            └────────┬─────────┘
                                                     │
                                                     ▼
                                            ┌──────────────────┐
                                            │ Merge all PDFs   │
                                            │ into one file    │
                                            └────────┬─────────┘
                                                     │
                                                     ▼
                                            ┌──────────────────┐
                                            │ Mark Request as  │
                                            │ COMPLETE         │
                                            │ Store PDF path   │
                                            └──────────────────┘
```

## Data Flow

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│ Patient  │────>│ PatientConsent│────>│RecordRequest │
│          │     │               │     │              │
│ - name   │     │ - consent_pdf │     │ - cities     │
│ - dob    │     │ - signature   │     │ - zips       │
│ - email  │     │               │     │ - status     │
│ - uuid   │     │               │     │ - compiled_  │
│          │     │               │     │   pdf_path   │
└──────────┘     └───────────────┘     └──────┬───────┘
                                              │
                                              │ has many
                                              ▼
                                     ┌────────────────┐
                                     │ProviderRequest │
                                     │                │
                                     │ - status       │
                                     │ - job_id       │
                                     │ - sent_at      │
                                     │ - responded_at │
                                     └───┬─────┬──────┘
                                         │     │
                          links to ┌────┘     └────┐ links to
                                   ▼               ▼
                            ┌──────────┐    ┌──────────┐
                            │ Provider │    │ FaxFile  │
                            │          │    │          │
                            │ - name   │    │ - pdf    │
                            │ - fax    │    │ - ocr    │
                            │ - npi    │    │ - patient│
                            │          │    │          │
                            └──────────┘    └──────────┘
```

## API Endpoints Map

```
Web Interface
├── GET  /                           → Landing page
├── GET  /register                   → Registration form
├── POST /register                   → Create patient
├── GET  /consent/{patient_id}       → Consent form
├── POST /consent/{patient_id}       → Save consent + signature
├── GET  /providers/{patient_id}     → Provider search form
├── POST /providers/{patient_id}     → Create request + send faxes
└── GET  /status/{request_id}        → View request status

Patient Portal
├── GET  /portal/{patient_uuid}                    → Portal home
├── GET  /portal/{patient_uuid}/download/{req_id}  → Download compiled
└── GET  /portal/{patient_uuid}/fax/{fax_id}       → Download fax

Webhooks
├── POST /ifax/receive               → Inbound fax webhook
└── POST /ifax/outbound-status       → Outbound status webhook

Health
└── GET  /healthz                    → Health check
```

## File Storage Structure

```
backend/
├── storage/
│   ├── signatures/
│   │   ├── sig_1.png              ← Patient signature images
│   │   ├── sig_2.png
│   │   └── sig_3.png
│   ├── releases/
│   │   ├── release_patient_1.pdf  ← Consent PDFs with signature
│   │   ├── release_patient_2.pdf
│   │   └── release_patient_3.pdf
│   ├── covers/
│   │   ├── cover_rr1_prov12.pdf   ← Fax cover sheets
│   │   ├── cover_rr1_prov13.pdf
│   │   └── cover_rr2_prov14.pdf
│   └── patient_1_request_1_records.pdf  ← Compiled records
├── received_faxes/
│   ├── 12345.pdf                  ← Incoming faxes (by job_id)
│   ├── 12346.pdf
│   └── 12347.pdf
└── logs/
    └── uvicorn-20251106-084430.log
```

## Database Tables

```
patients
├── id (PK)
├── uuid (unique)
├── first_name
├── last_name
├── email
├── phone
├── date_of_birth
└── created_at

patient_consents
├── id (PK)
├── patient_id (FK → patients.id)
├── release_text_version
├── consent_pdf_path        ← MUST NOT BE NULL
├── signature_image_path    ← MUST NOT BE NULL
├── signed_at
├── ip_address
└── user_agent

providers
├── id (PK)
├── npi
├── name
├── type
├── address_line1
├── city
├── state
├── postal_code
├── phone
├── fax
└── source (nppes | manual)

record_requests
├── id (PK)
├── patient_id (FK → patients.id)
├── status (pending | in_progress | complete)
├── requested_cities
├── requested_zips
├── release_pdf_path
├── compiled_pdf_path
├── created_at
└── completed_at

provider_requests
├── id (PK)
├── record_request_id (FK → record_requests.id)
├── provider_id (FK → providers.id)
├── fax_number_used
├── status (queued | fax_sent | fax_delivered | fax_failed | response_received)
├── outbound_job_id
├── sent_at
├── delivered_at
├── inbound_fax_id (FK → fax_files.id)
├── responded_at
└── failed_reason

fax_files
├── id (PK)
├── patient_id (FK → patients.id)
├── job_id
├── transaction_id
├── sender
├── receiver
├── received_time
├── file_path
├── pdf_data (binary)
└── ocr_text
```

## Technology Stack

```
┌─────────────────────────────────────────┐
│           Frontend (Templates)          │
│  HTML5 + Jinja2 + Vanilla JavaScript   │
└────────────┬────────────────────────────┘
             │ HTTP/HTTPS
             ▼
┌─────────────────────────────────────────┐
│        FastAPI Application              │
│  - Async/await                          │
│  - Pydantic validation                  │
│  - SQLAlchemy ORM                       │
└────────────┬────────────────────────────┘
             │
             ├─────────────────┬──────────────┬────────────────┐
             ▼                 ▼              ▼                ▼
    ┌────────────┐   ┌────────────┐  ┌──────────┐   ┌─────────────┐
    │ PostgreSQL │   │   iFax     │  │  NPPES   │   │ File System │
    │  or SQLite │   │    API     │  │   API    │   │   Storage   │
    └────────────┘   └────────────┘  └──────────┘   └─────────────┘
                             │
                             ▼
                     ┌────────────┐
                     │   OCR      │
                     │ Tesseract  │
                     │  Poppler   │
                     └────────────┘
```

This visual guide shows the complete application flow from user interaction to data processing!
