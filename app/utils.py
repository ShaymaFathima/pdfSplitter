import re
import os
import shutil
from typing import List, Tuple
import fitz
import cv2
import numpy as np
import uuid
import pytesseract
from datetime import datetime
from fastapi import UploadFile, HTTPException
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from functools import lru_cache
import aiofiles
import asyncio
import logging
from pdf2image import convert_from_path
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
#tesseract_path = shutil.which("tesseract")
#pytesseract.tesseract_cmd = tesseract_path


#poppler_path = shutil.which("pdftoppm")
poppler_path = "C:\\Users\\moham\\Downloads\\Release-24.08.0-0\\poppler-24.08.0\\Library\\bin"


def convert_pdf_to_images(pdf_path):
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap()
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        images.append(img)
    doc.close()
    return images

def extract_text_from_region(image, bbox, lang="eng"):
    x0, y0, x1, y1 = bbox
    cropped_image = image[y0:y1, x0:x1]
    text = pytesseract.image_to_string(cropped_image, lang=lang)
    return text.strip()

@lru_cache(maxsize=None)
def get_pdf_page_size(pdf_path):
    # Cache page size calculations
    doc = fitz.open(pdf_path)
    page = doc[0]
    width, height = page.rect.width, page.rect.height
    doc.close()
    return width, height

def match_logo_template(cropped_image, logo_templates):
    for logo_template in logo_templates:
        if logo_template is None or cropped_image is None:
            continue
        result = cv2.matchTemplate(cropped_image, logo_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if max_val >= 0.4:
            return max_val
    return 0

def identify_template(page_image, logo_templates):
    templates = {
        "Cheque": {
            "type": "logo_and_text",
            "logo_coords": (430, 0, 595, 100),  # Coordinates for the logo
            "text_coords": (0, 50, 595, 200),  # Coordinates for the text
            "keywords": ["CHEQUE", "Date"],
            "logo_threshold": 0.3,
            "text_match_threshold": 2
        },
        "Internal Bank Advice": {
            "type": "text",
            "coords": (0, 100, 595, 350),
            "keywords": ["INTERNAL BANK ADVICE", "DATE", "BANK NAME", "BRANCH NUMBER", "ACCOUNT NUMBER"]
        },
       "Staff Form": {
            "type": "structural",
            "regions": [
                {
                    "coords": (0, 300, 595, 400),  # Table header region
                    "keywords": ["beneficiary name", "account no", "branch no", "amount sr"],
                    "minimum_matches": 2
                },
                {
                    "coords": (0, 250, 595, 600),  # Main text region
                    "keywords": ["please arrange to transfer", "please debit the total amount", "authorized signature"],
                    "minimum_matches": 1
                },
                {
                    "coords": (0, 100, 595, 350),  # Voucher area
                    "keywords": ["voucher no"],
                    "minimum_matches": 1
                }
            ],
            "required_matches": 1  
        },
    }

    for template_name, details in templates.items():
        if details["type"] == "logo_and_text":
            # Check for logo match
            x0, y0, x1, y1 = details["logo_coords"]
            cropped_image = page_image[y0:y1, x0:x1]
            
            match_score = match_logo_template(cropped_image, logo_templates[template_name])
            
            logo_threshold = details.get("logo_threshold", 0.3)

            # Check for text match
            x0, y0, x1, y1 = details["text_coords"]
            extracted_text = extract_text_from_region(page_image, (x0, y0, x1, y1))
            extracted_text_lower = extracted_text.lower()
            keywords_lower = [keyword.lower() for keyword in details["keywords"]]
            keyword_matches = sum(1 for keyword in keywords_lower if keyword in extracted_text_lower)

            text_match_threshold = details.get("text_match_threshold", 1)
            if (match_score > logo_threshold and 
                keyword_matches >= text_match_threshold):
                return template_name

        elif details["type"] == "logo":
            x0, y0, x1, y1 = details["coords"]
            cropped_image = page_image[y0:y1, x0:x1]
            match_score = match_logo_template(cropped_image, logo_templates[template_name])
            if match_score > 0.5:
                return template_name

        elif details["type"] == "text":
            x0, y0, x1, y1 = details["coords"]
            extracted_text = extract_text_from_region(page_image, (x0, y0, x1, y1))
            extracted_text_lower = extracted_text.lower()
            keywords_lower = [keyword.lower() for keyword in details["keywords"]]

            if all(keyword in extracted_text_lower for keyword in keywords_lower):
                return template_name

        elif details["type"] == "structural":
            matches = 0
            # Check each region for its required keywords
            for region in details["regions"]:
                x0, y0, x1, y1 = region["coords"]
                extracted_text = extract_text_from_region(page_image, (x0, y0, x1, y1))
                extracted_text_lower = extracted_text.lower()
                keyword_matches = sum(1 for keyword in region["keywords"]
                                   if keyword.lower() in extracted_text_lower)
                if keyword_matches >= region["minimum_matches"]:
                    matches += 1

            if matches >= details["required_matches"]:
                return template_name

    return None

def identify_template_wrapper(args):
    page, logo_templates = args
    return identify_template(page, logo_templates)

def find_splitting_page_numbers(pdf_path, logo_templates):
    pages = convert_pdf_to_images(pdf_path)  
    split_pages = []  
    sub_doc_start = 0  

    page_args = [(page, logo_templates) for page in pages]
    with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        templates = list(executor.map(identify_template_wrapper, page_args))

    # Process identified templates sequentially to maintain original splitting logic
    for i, template in enumerate(templates):
        if template:
            if sub_doc_start != i:
                split_pages.append(sub_doc_start + 1)
            sub_doc_start = i 
    
    split_pages.append(sub_doc_start + 1)  
    
    return split_pages

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
def load_templates():
    cheque_template = os.path.join(DATA_DIR, "cheque1.pdf")
    bank_advice_template = os.path.join(DATA_DIR, "iba.pdf")
    staff_form_template = os.path.join(DATA_DIR, "sf.pdf")
    
    cheque_image = convert_pdf_to_images(cheque_template)[0]
    bank_advice_image = convert_pdf_to_images(bank_advice_template)[0]
    staff_form_image = convert_pdf_to_images(staff_form_template)[0]
    
    return cheque_image, bank_advice_image, staff_form_image


def resize_image(image, width, height):
    return cv2.resize(image, (int(width), int(height)))

@lru_cache(maxsize=1)
def load_and_prepare_templates(width, height):
    """Cached and optimized template loading"""
    cheque, bank_advice, staff_form = load_templates()
    
    cheque_resized = resize_image(cheque, width, height)
    bank_advice_resized = resize_image(bank_advice, width, height)
    staff_form_resized = resize_image(staff_form, width, height)
    
    return {
        "Cheque": [cheque_resized],
        "Internal Bank Advice": [bank_advice_resized],
        "Staff Form": [staff_form_resized]
    }


def preprocess_file(file_path):
    target_width, target_height = get_pdf_page_size(file_path)
    logo_templates = load_and_prepare_templates(target_width, target_height)
    splitting_page_numbers = find_splitting_page_numbers(file_path, logo_templates)
    return splitting_page_numbers


# Save file asynchronously with aiofiles
async def save_file(file: UploadFile, file_path: str):
    """Asynchronously save the uploaded file to the filesystem."""
    async with aiofiles.open(file_path, 'wb') as f:
        while chunk := await file.read(8 * 1024 * 1024):  # Read in 8MB chunks
            await f.write(chunk)


def list_folders(directory: str) -> List[str]:
    if not os.path.exists(directory):
        return []
    return [folder for folder in os.listdir(directory) if os.path.isdir(os.path.join(directory, folder))]


def split_and_save_pdfs(pdf_details: List[dict]) -> List[str]:
    base_uploads_dir = os.path.join("app", "uploads")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    split_folder = os.path.join(base_uploads_dir, "split", timestamp)
    os.makedirs(split_folder, exist_ok=True)

    split_files = []
    for pdf_info in pdf_details:
        pdf_path = pdf_info["pdf_path"]
        split_numbers = pdf_info["split_numbers"]

        # Validate the PDF path
        if not os.path.exists(pdf_path):
            raise HTTPException(status_code=404, detail=f"PDF not found: {pdf_path}")
        
        # Open the PDF
        pdf = fitz.open(pdf_path)
        total_pages = pdf.page_count
       
        # Ensure split numbers are valid
        split_numbers = sorted(set(split_numbers))  # Remove duplicates and sort
        split_numbers = [s for s in split_numbers if 1 <= s <= total_pages]  # Filter out-of-bounds
        
        ranges = []
        for i in range(len(split_numbers)):
            if i == len(split_numbers) - 1:
                ranges.append((split_numbers[i] - 1, total_pages - 1))
            else:
                 ranges.append((split_numbers[i] - 1, split_numbers[i + 1] - 2))
       
        # Split the PDF into sub-documents
        for index, (start_page, end_page) in enumerate(ranges):
            writer = fitz.open()

            # Add pages to the new sub-document
            for page_number in range(start_page, end_page + 1): 
                writer.insert_pdf(pdf, from_page=page_number, to_page=page_number)

            # Skip empty sub-documents 
            if len(writer) == 0: 
                writer.close()
                continue

            # Save the sub-document
            split_filename = f"split_{os.path.basename(pdf_path).replace('.pdf', '')}_{index + 1}.pdf"
            split_file_path = os.path.join(split_folder, split_filename)
            writer.save(split_file_path)
            writer.close()

            # Append the file path to the result list
            split_files.append(split_file_path)
             
        pdf.close()

    # Adjust paths to start from 'uploads'
    split_files = [os.path.relpath(path, base_uploads_dir) for path in split_files]
    return {"timestamp": timestamp, "split_files": split_files}
    


def extract_text_from_pdf(pdf_path):
    images = convert_from_path(pdf_path, first_page=1, last_page=1, dpi=300, poppler_path=poppler_path)
    if images:
        # OCR on the first page image with English only
        text = pytesseract.image_to_string(images[0], lang='eng')
        return text
    return ""


def extract_voucher_number_and_date(text):
    """Extract voucher number and date from the extracted text."""
    voucher_pattern = r'\b(\d{2})\D*(\d{6})\b'
    date_pattern = r'(?i)date[:\s]*(\d{1,2}/\d{1,2}/\d{4}|\d{1,2} \w+ \d{4}|\d{1,2}-\w+-\d{4}|\d{4}-\d{1,2}-\d{1,2})'

    voucher_match = re.search(voucher_pattern, text)
    date_match = re.search(date_pattern, text)

    if voucher_match:
        part1 = re.sub(r"[^\d]", "", voucher_match.group(1))
        part2 = re.sub(r"[^\d]", "", voucher_match.group(2))
        voucher_number = f"{part1}_{part2}"
    else:
        voucher_number = None

    if date_match:
        date_str = date_match.group(1)
        try:
            # Try parsing different date formats
            if '/' in date_str:
                # DD/MM/YYYY
                date_obj = datetime.strptime(date_str, '%d/%m/%Y')
            elif '-' in date_str and len(date_str.split('-')[0]) == 4:
                # YYYY-MM-DD
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            else:
                # Remove any hyphens and try parsing as DD Month YYYY
                date_str = date_str.replace('-', ' ')
                date_obj = datetime.strptime(date_str, '%d %B %Y')
            
            # Format the date consistently for filename
            date = date_obj.strftime('%Y-%m-%d')
        except ValueError:
            # If parsing fails, return the original matched string
            date = date_str.replace('/', '-').replace(' ', '-')
    else:
        
        date = None

    return voucher_number, date


def create_subfolders(base_folder: str) -> Tuple[str, str]:
    """
    Create success and failure subfolders within the given base folder.
    Returns the paths to the success and failure subfolders.
    """
    success_folder = os.path.join(base_folder, "success")
    failure_folder = os.path.join(base_folder, "failure")
    os.makedirs(success_folder, exist_ok=True)
    os.makedirs(failure_folder, exist_ok=True)
    return success_folder, failure_folder


def process_file(file_path: str, success_folder: str, failure_folder: str) -> Tuple[str, str]:
    """
    Process a file: extract metadata and move to success or failure folder.
    Returns the new file path (if successful) or the failure file path.
    """
    try:
        # Simulated metadata extraction
        text = extract_text_from_pdf(file_path)
        voucher_number, date = extract_voucher_number_and_date(text)

        if voucher_number and date:
            new_filename = f"{voucher_number}_{date}.pdf"
            new_path = os.path.join(success_folder, new_filename)
            shutil.move(file_path, new_path)  # Move to success folder
            return new_path, None
        else:
            failure_path = os.path.join(failure_folder, os.path.basename(file_path))
            shutil.move(file_path, failure_path)  # Move to failure folder
            return None, failure_path
    except Exception as e:
        failure_path = os.path.join(failure_folder, os.path.basename(file_path))
        shutil.move(file_path, failure_path)  # Move to failure folder
        return None, failure_path


def handle_files_in_folder(folder_path: str, success_folder: str, failure_folder: str) -> Tuple[List[str], List[str]]:
    """
    Handle all files in a folder, renaming and categorizing into success and failure.
    Returns lists of success and failure file paths.
    """
    renamed_files = []
    failed_files = []

    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)
        if not os.path.isfile(file_path):  # Skip directories
            continue

        success, failure = process_file(file_path, success_folder, failure_folder)
        if success:
            renamed_files.append(success)
        if failure:
            failed_files.append(failure)

    return renamed_files, failed_files