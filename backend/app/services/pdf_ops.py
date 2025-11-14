# app/services/pdf_ops.py - v2.0 Professional Templates
"""
PDF Operations Service

Generates professional medical records request documents:
1. HIPAA-compliant release authorization forms
2. Professional fax cover sheets
3. Searchable PDFs from OCR
4. PDF merging and aggregation

Version 2.0: Enhanced templates with full HIPAA compliance
"""

import os
import subprocess
import shutil
from typing import List, Optional
from datetime import datetime
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor


def generate_release_pdf(
        output_path: str,
        *,
        patient_name: str,
        dob: str,
        email: str,
        phone: str,
        signature_image_path: str,
        address: str = "",
        # Initials for sensitive categories
        initial_hiv: str = "",
        initial_genetic: str = "",
        initial_sud: str = "",
        initial_mental: str = "",
        initial_psychotherapy: str = "",
        # Record selections
        records_all: bool = True,
        records_abstract: bool = False,
        records_clinic: bool = False,
        records_lab: bool = False,
        records_radiology: bool = False,
        records_billing: bool = False,
) -> str:
    """
    Generate a professional HIPAA-compliant release authorization form.

    This creates a complete, legally-compliant authorization document that matches
    the Veritas One Release Form v2 template.
    """
    c = pdf_canvas.Canvas(output_path, pagesize=LETTER)
    width, height = LETTER

    # Colors
    header_color = HexColor('#1a1a1a')
    section_color = HexColor('#2c5aa0')
    text_color = HexColor('#333333')

    # Current date
    current_date = datetime.now().strftime("%B %d, %Y")

    # ===== PAGE 1: Main Authorization Form =====

    # Header
    c.setFillColor(header_color)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 0.7 * inch,
                        "AUTHORIZATION FOR RELEASE OF PROTECTED OR PRIVILEGED")
    c.drawCentredString(width / 2, height - 0.95 * inch,
                        "HEALTH INFORMATION AND PATIENT-DIRECTED ACCESS REQUEST")
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, height - 1.15 * inch,
                        "(VERITAS ONE, INC.)")

    # Instruction text
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(text_color)
    c.drawCentredString(width / 2, height - 1.4 * inch,
                        "Please print all information clearly in order to process your request in a timely manner.")

    # Section A: Patient Information
    y_pos = height - 1.8 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "A. PATIENT INFORMATION")

    y_pos -= 0.25 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)

    # Patient Name
    c.drawString(0.9 * inch, y_pos, "Patient Name:")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * inch, y_pos, patient_name)

    # DOB and MRN
    y_pos -= 0.2 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, f"Date of Birth: {dob}")
    c.drawString(4 * inch, y_pos, "Medical Record #: _______________")

    # Address
    y_pos -= 0.2 * inch
    if address:
        c.drawString(0.9 * inch, y_pos, f"Address: {address}")
    else:
        c.drawString(0.9 * inch, y_pos, "Address: _________________________________________________")

    # Phone and Email
    y_pos -= 0.2 * inch
    c.drawString(0.9 * inch, y_pos, f"Preferred Phone #: {phone or '_______________'}")
    c.drawString(4 * inch, y_pos, f"Email: {email or '_______________'}")

    # Purpose
    y_pos -= 0.25 * inch
    c.drawString(0.9 * inch, y_pos,
                 "PURPOSE (check one):  ☐ Medical Care   ☐ Insurance   ☐ Legal   ☒ Personal   ☐ School   ☐ Other: _______")

    # Section B: Permission to Share
    y_pos -= 0.4 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "B. PERMISSION TO SHARE")

    y_pos -= 0.25 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, "Records FROM (Disclosing Provider/Facility):")

    y_pos -= 0.18 * inch
    c.drawString(1.1 * inch, y_pos, "Site/Location: (Will be filled in based on provider selection)")
    y_pos -= 0.15 * inch
    c.drawString(1.1 * inch, y_pos, "Practice Name: _________________________________")

    y_pos -= 0.2 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, "Send records TO (Designated Recipient):")

    y_pos -= 0.18 * inch
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1.1 * inch, y_pos, "Veritas One, Inc.")
    c.setFont("Helvetica", 9)
    c.drawString(2.3 * inch, y_pos, "— acting as my agent to receive/consolidate and deliver records to me")

    y_pos -= 0.15 * inch
    c.drawString(1.1 * inch, y_pos, "Fax (secure): [Will be provided]")
    c.drawString(4 * inch, y_pos, "Phone: [Will be provided]")

    # Section C: Information to be Released
    y_pos -= 0.35 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "C. INFORMATION TO BE RELEASED (check all that apply; specify dates)")

    y_pos -= 0.2 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)

    # Record checkboxes
    checkbox_checked = "☒"
    checkbox_empty = "☐"

    c.drawString(0.9 * inch, y_pos,
                 f"{checkbox_checked if records_all else checkbox_empty} ALL RECORDS (Designated Record Set), ALL DATES (includes clinical + billing; radiology reports & images)")

    y_pos -= 0.18 * inch
    c.drawString(0.9 * inch, y_pos,
                 f"{checkbox_checked if records_abstract else checkbox_empty} Medical record abstract (H&P, operative reports, consults, test reports, discharge summaries)")

    y_pos -= 0.18 * inch
    c.drawString(0.9 * inch, y_pos,
                 f"{checkbox_checked if records_clinic else checkbox_empty} Clinic / visit notes   Date(s): __________")

    y_pos -= 0.18 * inch
    c.drawString(0.9 * inch, y_pos,
                 f"{checkbox_checked if records_lab else checkbox_empty} Laboratory   Date(s): __________")

    y_pos -= 0.18 * inch
    c.drawString(0.9 * inch, y_pos,
                 f"{checkbox_checked if records_radiology else checkbox_empty} Radiology REPORTS and IMAGES (DICOM/CD/portal acceptable)   Date(s): __________")

    y_pos -= 0.18 * inch
    c.drawString(0.9 * inch, y_pos,
                 f"{checkbox_checked if records_billing else checkbox_empty} Billing / claims   Date(s): __________")

    # Section D: Sensitive Information
    y_pos -= 0.35 * inch
    if y_pos < 2 * inch:  # Start new page if needed
        c.showPage()
        y_pos = height - 1 * inch

    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "D. SENSITIVE INFORMATION — RELEASE ONLY IF INITIALED BY PATIENT")

    y_pos -= 0.2 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)

    # HIV/AIDS
    c.drawString(0.9 * inch, y_pos,
                 f"☐ HIV/AIDS testing, diagnosis, or treatment — Initials: {initial_hiv or '________'}")

    y_pos -= 0.18 * inch
    c.drawString(0.9 * inch, y_pos,
                 f"☐ Genetic testing/results — Initials: {initial_genetic or '________'}")

    y_pos -= 0.18 * inch
    c.drawString(0.9 * inch, y_pos,
                 f"☐ Substance Use Disorder records (42 C.F.R. Part 2) — Initials: {initial_sud or '________'}")

    y_pos -= 0.15 * inch
    c.setFont("Helvetica-Bold", 8)
    c.drawString(1.1 * inch, y_pos,
                 "NOTICE: Federal rules prohibit further disclosure of Part 2 records unless expressly permitted")
    y_pos -= 0.12 * inch
    c.drawString(1.1 * inch, y_pos,
                 "by the patient's written consent or as otherwise allowed by Part 2.")

    y_pos -= 0.2 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos,
                 f"☐ Mental/behavioral health information (non-psychotherapy notes) — Initials: {initial_mental or '________'}")

    y_pos -= 0.18 * inch
    c.drawString(0.9 * inch, y_pos,
                 f"☐ Psychotherapy notes (HIPAA-defined) — SEPARATE specific authorization required — Initials: {initial_psychotherapy or '________'}")

    # Continue to next page for Section E and signature
    c.showPage()
    y_pos = height - 1 * inch

    # Section E: Acknowledgments
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "E. ACKNOWLEDGMENTS, EXPIRATION, AND REQUIRED HIPAA STATEMENTS")

    y_pos -= 0.25 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 8)

    acknowledgments = [
        ("• Right of Access / Form & Format:",
         "I am requesting access and directing transmission of my records to Veritas One. Please provide the copy in the form and format requested if readily producible, otherwise in a readable alternative format agreed upon (45 C.F.R. §164.524(c)(2)). Please act as promptly as possible and no later than 30 days from receipt (one 30-day extension only with written notice). Fees must be reasonable and cost-based."),

        ("• Voluntary/No Conditioning:",
         "My treatment, payment, enrollment, or eligibility for benefits will not be conditioned on signing this authorization (subject to HIPAA's limited exceptions)."),

        ("• Revocation:",
         "I may revoke this authorization at any time by written notice to Veritas One and to the Disclosing Provider, except to the extent action has been taken in reliance."),

        ("• Redisclosure:",
         "Information disclosed to the recipient may be redisclosed and may no longer be protected by HIPAA, except as otherwise restricted by law (including 42 C.F.R. Part 2 for SUD records)."),

        ("• Expiration:",
         "This authorization expires 6 months (180 days) from the date signed unless I specify an earlier date/event."),
    ]

    for title, text in acknowledgments:
        c.setFont("Helvetica-Bold", 8)
        c.drawString(0.9 * inch, y_pos, title)
        y_pos -= 0.12 * inch

        c.setFont("Helvetica", 8)
        # Word wrap the text
        words = text.split()
        line = ""
        for word in words:
            test_line = line + word + " "
            if c.stringWidth(test_line, "Helvetica", 8) < 6.5 * inch:
                line = test_line
            else:
                c.drawString(1.1 * inch, y_pos, line)
                y_pos -= 0.12 * inch
                line = word + " "
        if line:
            c.drawString(1.1 * inch, y_pos, line)
        y_pos -= 0.2 * inch

    # Signature Section
    y_pos -= 0.2 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "SIGNATURES")

    y_pos -= 0.3 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)

    # Patient signature
    if os.path.exists(signature_image_path):
        try:
            c.drawImage(signature_image_path, 0.9 * inch, y_pos - 0.6 * inch,
                        width=2.5 * inch, height=0.6 * inch, preserveAspectRatio=True)
        except:
            pass

    c.line(0.9 * inch, y_pos, 4 * inch, y_pos)
    y_pos -= 0.15 * inch
    c.setFont("Helvetica", 8)
    c.drawString(0.9 * inch, y_pos, "Patient Signature")
    c.drawString(4.5 * inch, y_pos, f"Date: {current_date}")

    y_pos -= 0.15 * inch
    c.drawString(0.9 * inch, y_pos, f"Print Name: {patient_name}")

    # Personal Representative section (if needed)
    y_pos -= 0.35 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, "If signed by Personal Representative:")
    y_pos -= 0.15 * inch
    c.drawString(0.9 * inch, y_pos, "Name/Relationship/Authority: _________________________________________________")
    y_pos -= 0.25 * inch
    c.line(0.9 * inch, y_pos, 4 * inch, y_pos)
    y_pos -= 0.15 * inch
    c.setFont("Helvetica", 8)
    c.drawString(0.9 * inch, y_pos, "Signature")
    c.drawString(4.5 * inch, y_pos, "Date: __________")

    # Footer - Facility Use Only
    y_pos -= 0.35 * inch
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.75 * inch, y_pos, "FACILITY USE ONLY")
    y_pos -= 0.15 * inch
    c.setFont("Helvetica", 8)
    c.drawString(0.9 * inch, y_pos,
                 "Date received: _______     Completed by: _______     Delivery method: ☐ Fax  ☐ Electronic  ☐ Mail     Completion date: _______")

    # Confidentiality notice at bottom
    y_pos = 0.5 * inch
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(width / 2, y_pos,
                        "This document contains protected health information. Handle in accordance with HIPAA Privacy Rule.")

    c.showPage()
    c.save()

    return output_path


def write_cover_sheet(
        path: str,
        *,
        patient_name: str,
        dob: str,
        request_id: int,
        patient_phone: str = "",
        patient_email: str = "",
        provider_name: str = "",
        provider_fax: str = "",
        provider_phone: str = "",
        total_pages: int = 2,
) -> str:
    """
    Generate a professional HIPAA-compliant fax cover sheet.

    This creates a cover sheet that matches the Veritas One Fax Cover Template
    with all required information for medical records requests.
    """
    c = pdf_canvas.Canvas(path, pagesize=LETTER)
    width, height = LETTER

    # Colors
    header_color = HexColor('#1a1a1a')
    section_color = HexColor('#2c5aa0')
    text_color = HexColor('#333333')
    highlight_color = HexColor('#f0f0f0')

    current_date = datetime.now().strftime("%B %d, %Y")

    # Header with company branding
    c.setFillColor(header_color)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 0.6 * inch, "VERITAS ONE, INC.")

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, height - 0.85 * inch,
                        "MEDICAL RECORDS REQUEST (PATIENT ACCESS) — FAX COVER")

    # Separator line
    c.setStrokeColor(section_color)
    c.setLineWidth(2)
    c.line(0.75 * inch, height - 1 * inch, width - 0.75 * inch, height - 1 * inch)

    # Return Information Section
    y_pos = height - 1.3 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y_pos, "RETURN FAX (SECURE):")
    c.setFillColor(text_color)
    c.setFont("Helvetica", 10)
    c.drawString(2.5 * inch, y_pos, "[Your Secure Fax Number]")

    y_pos -= 0.2 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y_pos, "ALTERNATE SECURE DELIVERY:")
    c.setFillColor(text_color)
    c.setFont("Helvetica", 10)
    c.drawString(2.5 * inch, y_pos, "secure@veritasone.com or SFTP")

    y_pos -= 0.2 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y_pos, "CONTACT (QUESTIONS):")
    c.setFillColor(text_color)
    c.setFont("Helvetica", 10)
    c.drawString(2.5 * inch, y_pos, "[Your Phone] | [Your Address]")

    # Recipient Information Box
    y_pos -= 0.4 * inch
    c.setFillColor(highlight_color)
    c.rect(0.75 * inch, y_pos - 0.7 * inch, width - 1.5 * inch, 0.9 * inch, fill=True, stroke=False)

    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.9 * inch, y_pos, "TO (HIM/ROI):")
    c.setFillColor(text_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * inch, y_pos, provider_name or "[PROVIDER NAME / DEPARTMENT]")

    y_pos -= 0.2 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, f"PROVIDER FAX: {provider_fax or '[PROVIDER FAX]'}")
    c.drawString(4 * inch, y_pos, f"PHONE: {provider_phone or '[PROVIDER PHONE]'}")

    y_pos -= 0.25 * inch
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.9 * inch, y_pos, "FROM:")
    c.setFont("Helvetica", 9)
    c.drawString(1.5 * inch, y_pos, "Veritas One, Inc. (designated agent for the patient)")

    y_pos -= 0.2 * inch
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.9 * inch, y_pos, "DATE:")
    c.setFont("Helvetica", 9)
    c.drawString(1.5 * inch, y_pos, current_date)
    c.drawString(3.5 * inch, y_pos, f"PAGES (INCLUDING COVER): {total_pages}")
    c.drawString(6 * inch, y_pos, f"REQUEST ID: {request_id}")

    # Patient Information Section
    y_pos -= 0.5 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "PATIENT INFORMATION")

    y_pos -= 0.25 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.9 * inch, y_pos, "PATIENT:")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * inch, y_pos, patient_name)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(5 * inch, y_pos, "DOB:")
    c.setFont("Helvetica", 10)
    c.drawString(5.6 * inch, y_pos, dob or "[DOB]")

    y_pos -= 0.2 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, f"PHONE: {patient_phone or '[PATIENT PHONE]'}")
    c.drawString(3 * inch, y_pos, f"EMAIL: {patient_email or '[PATIENT EMAIL]'}")

    y_pos -= 0.15 * inch
    c.drawString(0.9 * inch, y_pos, "OPTIONAL IDENTIFIERS: MRN [____] | LAST 4 SSN [____]")

    # Records Requested Section
    y_pos -= 0.35 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "RECORDS REQUESTED (DESIGNATED RECORD SET)")

    y_pos -= 0.2 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, "☒ ALL RECORDS, ALL DATES (clinical + billing; radiology reports & images)")

    y_pos -= 0.15 * inch
    c.drawString(0.9 * inch, y_pos, "☐ DATE RANGE: [FROM] to [TO]")

    y_pos -= 0.15 * inch
    c.drawString(0.9 * inch, y_pos, "☐ SPECIFIC DOCUMENTS: __________")

    # Sensitive Categories Section
    y_pos -= 0.35 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75 * inch, y_pos, "SENSITIVE CATEGORIES (RELEASE IF INITIALED ON ATTACHED AUTHORIZATION)")

    y_pos -= 0.2 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, "HIV/STD _____   GENETIC _____   REPRODUCTIVE/SEXUAL HEALTH _____")

    y_pos -= 0.15 * inch
    c.drawString(0.9 * inch, y_pos, "MENTAL/BEHAVIORAL HEALTH (non-psychotherapy) _____   SUD/42 CFR PART 2 _____")

    y_pos -= 0.15 * inch
    c.setFont("Helvetica-Bold", 8)
    c.drawString(0.9 * inch, y_pos, "NOTE: PSYCHOTHERAPY NOTES REQUIRE A SEPARATE SPECIFIC AUTHORIZATION.")

    # Delivery Section
    y_pos -= 0.3 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y_pos, "DELIVERY (FORM/FORMAT REQUESTED)")

    y_pos -= 0.18 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos,
                 "☒ Fax to return number above   ☒ Secure electronic delivery (upload/SFTP/Direct/portal)   ☐ Encrypted email")

    # Authority & Timing
    y_pos -= 0.3 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y_pos, "AUTHORITY & TIMING (HIPAA RIGHT OF ACCESS)")

    y_pos -= 0.18 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 8)
    c.drawString(0.9 * inch, y_pos,
                 "Patient-directed access request under 45 C.F.R. §164.524. Please respond as promptly as possible")
    y_pos -= 0.12 * inch
    c.drawString(0.9 * inch, y_pos,
                 "and no later than 30 days from receipt (one 30-day extension with written notice). Fees must be reasonable and cost-based.")

    # Attachments
    y_pos -= 0.3 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y_pos, "ATTACHMENTS")

    y_pos -= 0.18 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 9)
    c.drawString(0.9 * inch, y_pos, "(1) Patient-signed HIPAA authorization (expires 180 days unless otherwise stated)")
    y_pos -= 0.15 * inch
    c.drawString(0.9 * inch, y_pos, "(2) [Optional] Photo ID")

    # Confidentiality Notice Box
    y_pos -= 0.35 * inch
    c.setFillColor(HexColor('#fff3cd'))
    c.rect(0.75 * inch, y_pos - 0.6 * inch, width - 1.5 * inch, 0.7 * inch, fill=True, stroke=True)

    c.setFillColor(HexColor('#856404'))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.9 * inch, y_pos - 0.15 * inch, "CONFIDENTIALITY NOTICE:")
    c.setFont("Helvetica", 8)
    c.drawString(0.9 * inch, y_pos - 0.3 * inch,
                 "This fax may contain protected health information (PHI). If you received it in error, notify the sender")
    c.drawString(0.9 * inch, y_pos - 0.42 * inch, "and destroy all copies.")

    # 42 CFR Part 2 Notice
    y_pos -= 0.9 * inch
    c.setFillColor(section_color)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.75 * inch, y_pos, "42 C.F.R. PART 2 NOTICE (IF APPLICABLE):")
    y_pos -= 0.15 * inch
    c.setFillColor(text_color)
    c.setFont("Helvetica", 8)
    c.drawString(0.9 * inch, y_pos,
                 "This information has been disclosed to you from records protected by 42 C.F.R. Part 2. Redisclosure is prohibited")
    y_pos -= 0.12 * inch
    c.drawString(0.9 * inch, y_pos, "unless permitted by the patient's consent or by Part 2.")

    # Footer
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(width / 2, 0.5 * inch,
                        f"Veritas One, Inc. | Medical Records Request | Page 1 of {total_pages} | Request ID: {request_id}")

    c.showPage()
    c.save()

    return path


def ocr_to_searchable_pdf(in_path: str, out_path: str) -> str:
    """
    Convert a PDF to searchable PDF using OCRmyPDF.
    Falls back to simple copy if OCRmyPDF is not available.
    """
    exe = shutil.which("ocrmypdf")
    if not exe:
        shutil.copyfile(in_path, out_path)
        return out_path

    try:
        subprocess.run(
            [exe, "--quiet", "--skip-text", in_path, out_path],
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError:
        # If OCR fails, just copy the original
        shutil.copyfile(in_path, out_path)

    return out_path


def merge_pdfs(pdf_paths: List[str], output_path: str) -> str:
    """
    Merge multiple PDF files into a single PDF.
    """
    from PyPDF2 import PdfMerger

    merger = PdfMerger()
    for pdf_path in pdf_paths:
        if os.path.exists(pdf_path):
            merger.append(pdf_path)

    merger.write(output_path)
    merger.close()

    return output_path