#!/usr/bin/env python3
"""
OCR Diagnostic Script

Run this to check if your OCR setup is working correctly.

Usage:
    python ocr_diagnostic.py [pdf_file]
    
If no PDF file is provided, it will just check dependencies.
"""

import sys
import os
import subprocess
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def check_command(command, version_flag='--version'):
    """Check if a command is available and get its version."""
    try:
        result = subprocess.run(
            [command, version_flag],
            capture_output=True,
            text=True,
            timeout=5
        )
        return True, result.stdout + result.stderr
    except FileNotFoundError:
        return False, f"{command} not found"
    except subprocess.TimeoutExpired:
        return False, f"{command} timed out"
    except Exception as e:
        return False, str(e)


def main():
    print("=" * 70)
    print("OCR DIAGNOSTIC TOOL")
    print("=" * 70)
    print()
    
    # Check Python version
    print(f"✓ Python: {sys.version.split()[0]}")
    print()
    
    # Check Tesseract
    print("Checking Tesseract OCR...")
    tesseract_ok, tesseract_info = check_command('tesseract')
    if tesseract_ok:
        # Extract version from output
        version_line = tesseract_info.split('\n')[0]
        print(f"✓ Tesseract: {version_line}")
    else:
        print(f"✗ Tesseract: {tesseract_info}")
        print("  Install with: brew install tesseract")
    print()
    
    # Check Poppler (pdftoppm)
    print("Checking Poppler (pdftoppm)...")
    poppler_ok, poppler_info = check_command('pdftoppm', '-v')
    if poppler_ok:
        # Extract version
        version_line = poppler_info.split('\n')[0] if poppler_info else "installed"
        print(f"✓ Poppler: {version_line}")
    else:
        print(f"✗ Poppler: {poppler_info}")
        print("  Install with: brew install poppler")
    print()
    
    # Check PIL/Pillow
    print("Checking Pillow (PIL)...")
    try:
        from PIL import Image
        import PIL
        print(f"✓ Pillow: {PIL.__version__}")
    except ImportError:
        print("✗ Pillow not installed")
        print("  Install with: pip install Pillow")
    print()
    
    # Overall status
    all_ok = tesseract_ok and poppler_ok
    
    if not all_ok:
        print("=" * 70)
        print("❌ OCR DEPENDENCIES MISSING")
        print("=" * 70)
        print()
        print("To fix, run:")
        if not tesseract_ok:
            print("  brew install tesseract")
        if not poppler_ok:
            print("  brew install poppler")
        print()
        return 1
    
    print("=" * 70)
    print("✅ ALL OCR DEPENDENCIES INSTALLED")
    print("=" * 70)
    print()
    
    # If PDF file provided, test OCR on it
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        
        if not os.path.exists(pdf_path):
            print(f"❌ File not found: {pdf_path}")
            return 1
        
        print(f"Testing OCR on: {pdf_path}")
        print("=" * 70)
        print()
        
        try:
            # Import here so we fail gracefully if not installed
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from app.services.ocr_service import extract_text_from_pdf
            
            print("Running OCR extraction...")
            text = extract_text_from_pdf(pdf_path)
            
            print(f"✅ Successfully extracted {len(text)} characters")
            print()
            print("First 500 characters:")
            print("-" * 70)
            print(text[:500])
            print("-" * 70)
            print()
            
            if len(text) == 0:
                print("⚠️  WARNING: No text extracted from PDF")
                print("   This could mean:")
                print("   - The PDF is an image without any text layer")
                print("   - The image quality is too poor for OCR")
                print("   - The PDF is empty")
                return 1
            
        except Exception as e:
            print(f"❌ OCR extraction failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return 1
    
    else:
        print("To test OCR on a PDF file, run:")
        print(f"  python {sys.argv[0]} /path/to/file.pdf")
        print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
