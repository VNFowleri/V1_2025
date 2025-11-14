"""
OCR Service

Handles text extraction from PDF files using Tesseract OCR.
Converts PDF pages to images and processes them for text extraction.
"""

import logging
from pathlib import Path
from typing import Optional
import os
import subprocess

logger = logging.getLogger(__name__)

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text from PDF using Tesseract OCR.
    
    Process:
    1. Convert PDF to images (one per page)
    2. Run Tesseract OCR on each image
    3. Concatenate all text
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Extracted text as string
        
    Raises:
        FileNotFoundError: If PDF doesn't exist
        RuntimeError: If OCR processing fails
    """
    if not os.path.exists(pdf_path):
        logger.error(f"❌ PDF file not found: {pdf_path}")
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    logger.info(f"Starting OCR extraction for: {pdf_path}")
    
    try:
        # Check if required tools are installed
        _check_ocr_dependencies()
        
        # Get file size for logging
        file_size = os.path.getsize(pdf_path)
        logger.info(f"PDF file size: {file_size} bytes")
        
        # Convert PDF to images and extract text
        text = _process_pdf_with_tesseract(pdf_path)
        
        if not text or len(text.strip()) == 0:
            logger.warning(f"⚠️ OCR returned empty text for {pdf_path}")
            return ""
        
        logger.info(f"✅ Successfully extracted {len(text)} characters from {pdf_path}")
        logger.debug(f"Text preview: {text[:200]}...")
        
        return text
        
    except Exception as e:
        logger.error(f"❌ OCR extraction failed for {pdf_path}: {str(e)}", exc_info=True)
        raise RuntimeError(f"OCR extraction failed: {str(e)}")


def _check_ocr_dependencies():
    """
    Check if required OCR tools are installed.
    
    Raises:
        RuntimeError: If required tools are missing
    """
    # Check for Tesseract
    try:
        result = subprocess.run(
            ['tesseract', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            raise RuntimeError("Tesseract not working properly")
        logger.debug(f"Tesseract version: {result.stdout.split()[1]}")
    except FileNotFoundError:
        logger.error("❌ Tesseract not found. Please install: brew install tesseract")
        raise RuntimeError("Tesseract not installed")
    except subprocess.TimeoutExpired:
        logger.error("❌ Tesseract check timed out")
        raise RuntimeError("Tesseract not responding")
    
    # Check for Poppler (pdftoppm)
    try:
        result = subprocess.run(
            ['pdftoppm', '-v'],
            capture_output=True,
            text=True,
            timeout=5
        )
        # pdftoppm returns version info on stderr
        logger.debug(f"Poppler installed: {result.stderr.split()[2] if result.stderr else 'unknown version'}")
    except FileNotFoundError:
        logger.error("❌ Poppler not found. Please install: brew install poppler")
        raise RuntimeError("Poppler not installed")
    except subprocess.TimeoutExpired:
        logger.error("❌ Poppler check timed out")
        raise RuntimeError("Poppler not responding")


def _process_pdf_with_tesseract(pdf_path: str) -> str:
    """
    Process PDF using Tesseract OCR.
    
    Uses pdftoppm to convert PDF to images, then runs Tesseract on each page.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Extracted text
    """
    import tempfile
    import shutil
    from PIL import Image
    
    # Create temporary directory for images
    temp_dir = tempfile.mkdtemp(prefix="ocr_")
    logger.debug(f"Created temp directory: {temp_dir}")
    
    try:
        # Convert PDF to images (one per page)
        logger.info("Converting PDF to images...")
        output_prefix = os.path.join(temp_dir, "page")
        
        # Use pdftoppm to convert PDF to PNG images
        # -png: output format
        # -r 300: resolution (DPI)
        result = subprocess.run(
            [
                'pdftoppm',
                '-png',
                '-r', '300',  # 300 DPI for good OCR quality
                pdf_path,
                output_prefix
            ],
            capture_output=True,
            text=True,
            timeout=60  # 60 second timeout
        )
        
        if result.returncode != 0:
            logger.error(f"❌ pdftoppm failed: {result.stderr}")
            raise RuntimeError(f"PDF to image conversion failed: {result.stderr}")
        
        # Find generated images
        image_files = sorted([
            f for f in os.listdir(temp_dir)
            if f.startswith('page-') and f.endswith('.png')
        ])
        
        if not image_files:
            logger.error("❌ No images generated from PDF")
            raise RuntimeError("No images generated from PDF")
        
        logger.info(f"Generated {len(image_files)} image(s) from PDF")
        
        # Run Tesseract on each image
        all_text = []
        
        for i, img_file in enumerate(image_files, 1):
            img_path = os.path.join(temp_dir, img_file)
            logger.debug(f"Processing page {i}/{len(image_files)}: {img_file}")
            
            try:
                # Preprocess image for better OCR
                image = Image.open(img_path)
                
                # Convert to grayscale
                image = image.convert('L')
                
                # Apply thresholding to binarize the image
                # This helps OCR by making text clearer
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(2.0)  # Increase contrast
                
                # Save preprocessed image
                preprocessed_path = os.path.join(temp_dir, f"preprocessed_{img_file}")
                image.save(preprocessed_path)
                
                # Run Tesseract
                result = subprocess.run(
                    [
                        'tesseract',
                        preprocessed_path,
                        'stdout',  # Output to stdout
                        '-l', 'eng',  # English language
                        '--psm', '1',  # Page segmentation mode: auto with OSD
                        '--oem', '3',  # OCR Engine Mode: default (LSTM)
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30  # 30 second timeout per page
                )
                
                if result.returncode != 0:
                    logger.warning(f"⚠️ Tesseract failed on page {i}: {result.stderr}")
                    continue
                
                page_text = result.stdout.strip()
                
                if page_text:
                    logger.debug(f"Page {i} extracted {len(page_text)} characters")
                    all_text.append(f"\n--- Page {i} ---\n{page_text}")
                else:
                    logger.warning(f"⚠️ No text extracted from page {i}")
                
            except Exception as e:
                logger.warning(f"⚠️ Error processing page {i}: {str(e)}")
                continue
        
        if not all_text:
            logger.error("❌ No text extracted from any page")
            return ""
        
        # Combine all text
        combined_text = "\n".join(all_text)
        logger.info(f"✅ Extracted total {len(combined_text)} characters from {len(all_text)} page(s)")
        
        return combined_text
        
    finally:
        # Clean up temporary directory
        try:
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to clean up temp directory: {e}")


def is_ocr_available() -> bool:
    """
    Check if OCR service is available.
    
    Returns:
        True if both Tesseract and Poppler are installed and working
    """
    try:
        _check_ocr_dependencies()
        return True
    except Exception as e:
        logger.warning(f"OCR not available: {str(e)}")
        return False


def test_ocr_service():
    """
    Test OCR service with diagnostic output.
    
    Useful for troubleshooting OCR setup.
    """
    logger.info("=== OCR Service Diagnostic ===")
    
    # Check dependencies
    logger.info("Checking dependencies...")
    try:
        _check_ocr_dependencies()
        logger.info("✅ All dependencies installed")
    except Exception as e:
        logger.error(f"❌ Dependencies check failed: {str(e)}")
        return
    
    # Check for test PDF
    test_pdf = "received_faxes/test.pdf"
    if os.path.exists(test_pdf):
        logger.info(f"Testing with: {test_pdf}")
        try:
            text = extract_text_from_pdf(test_pdf)
            logger.info(f"✅ OCR test successful: {len(text)} characters")
            logger.info(f"Preview: {text[:200]}...")
        except Exception as e:
            logger.error(f"❌ OCR test failed: {str(e)}")
    else:
        logger.info(f"No test PDF found at {test_pdf}")
    
    logger.info("=== End Diagnostic ===")


if __name__ == "__main__":
    # Run diagnostic when executed directly
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    test_ocr_service()
