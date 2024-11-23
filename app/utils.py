import re
import os
import shutil
from typing import List
import fitz
import cv2
import numpy as np
from PyPDF2 import PdfReader, PdfWriter
import pytesseract
from datetime import datetime
from pdf2image import convert_from_path
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

poppler_path = "C:\\Users\\moham\\Downloads\\Release-24.08.0-0\\poppler-24.08.0\\Library\\bin"

def convert_pdf_to_images(pdf_path):
  doc = fitz.open(pdf_path)
  images = []
  for page in doc:
    pix = page.get_pixmap()
    img = np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height, pix.width, 3)
    images.append(img)
  return images

def extract_text_from_region(image, bbox, lang="eng"):
    x0, y0, x1, y1 = bbox
    cropped_image = image[y0:y1, x0:x1]
    text = pytesseract.image_to_string(cropped_image, lang=lang)
    return text.strip()

def get_pdf_page_size(pdf_path):
    doc = fitz.open(pdf_path)
    page = doc[0]
    return page.rect.width, page.rect.height

def resize_image(image, target_width, target_height):
    return cv2.resize(image, (int(target_width), int(target_height)))

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
            "keywords": ["CHEQUE", "Date"]
        },
        "Internal Bank Advice": {
            "type": "text",
            "coords": (0, 100, 595, 350),
            "keywords": ["INTERNAL BANK ADVICE", "DATE", "BANK NAME", "BRANCH NUMBER", "ACCOUNT NUMBER"]
        },
        "Staff Form": {
            "type": "text",
            "coords": (0, 100, 595, 350),
            "keywords": ["Voucher No", "Date", "Subject", "Gentlemen:", "BENEFICIARY NAME", "ACCOUNT NO.", "BRANCH NO.", "AMOUNT SR"]
        },
    }

    for template_name, details in templates.items():
        if details["type"] == "logo_and_text":
            # Check for logo match
            x0, y0, x1, y1 = details["logo_coords"]
            cropped_image = page_image[y0:y1, x0:x1]
            match_score = match_logo_template(cropped_image, logo_templates[template_name])
            
            # Check for text match
            x0, y0, x1, y1 = details["text_coords"]
            extracted_text = extract_text_from_region(page_image, (x0, y0, x1, y1))
            extracted_text_lower = extracted_text.lower()
            keywords_lower = [keyword.lower() for keyword in details["keywords"]]
            
            # Check if all keywords are present in the extracted text
            if match_score > 0.4 and all(keyword in extracted_text_lower for keyword in keywords_lower):
                return template_name

        elif details["type"] == "logo":
            x0, y0, x1, y1 = details["coords"]
            cropped_image = page_image[y0:y1, x0:x1]
            match_score = match_logo_template(cropped_image, logo_templates[template_name])
            if match_score > 0.4:
                return template_name
        
        elif details["type"] == "text":
            x0, y0, x1, y1 = details["coords"]
            extracted_text = extract_text_from_region(page_image, (x0, y0, x1, y1))
            extracted_text_lower = extracted_text.lower()
            keywords_lower = [keyword.lower() for keyword in details["keywords"]]
            
            if all(keyword in extracted_text_lower for keyword in keywords_lower):
                return template_name

    return None



def find_splitting_page_numbers(pdf_path, logo_templates):
    pages = convert_pdf_to_images(pdf_path)  
    split_pages = []  
    sub_doc_start = 0  

    for i, page_image in enumerate(pages):
        template = identify_template(page_image, logo_templates)  # Identify the template for each page
        if template:  # If a template match is found, it indicates a split
            if sub_doc_start != i:
                split_pages.append(sub_doc_start + 1)  # Add the split page number (1-based index)
            sub_doc_start = i  # Update sub-document start to current page
    
    # Append the last split page after the loop ends
    split_pages.append(sub_doc_start + 1)  
    
    return split_pages  # Return the list of splitting page numbers


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
def load_templates():
    cheque_template = os.path.join(DATA_DIR, "cheque1.pdf")
    bank_advice_template = os.path.join(DATA_DIR, "iba.pdf")
    staff_form_template = os.path.join(DATA_DIR, "sf.pdf")
    
    cheque_image = convert_pdf_to_images(cheque_template)[0]
    bank_advice_image = convert_pdf_to_images(bank_advice_template)[0]
    staff_form_image = convert_pdf_to_images(staff_form_template)[0]
    
    return cheque_image, bank_advice_image, staff_form_image

def extract_text_from_pdf(pdf_path):
    images = convert_from_path(pdf_path, first_page=1, last_page=1, dpi=300, poppler_path=poppler_path)
    if images:
        # OCR on the first page image with English only
        text = pytesseract.image_to_string(images[0], lang='eng')
        return text
    return ""


def list_folders(directory: str) -> List[str]:
    if not os.path.exists(directory):
        return []
    return [folder for folder in os.listdir(directory) if os.path.isdir(os.path.join(directory, folder))]


def list_files_in_folder(folder_path: str):
    if not os.path.exists(folder_path):
        return []
    return [file for file in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, file))]


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


def split_and_rename_pdfs(pdf_path, split_numbers, success_folder, failure_folder):
    """
    Splits a PDF based on known page numbers and renames files based on voucher and date.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    # Create timestamped subfolders for success and failure
    success_subfolder = os.path.join(success_folder, timestamp)
    failure_subfolder = os.path.join(failure_folder, timestamp)

    os.makedirs(success_subfolder, exist_ok=True)
    os.makedirs(failure_subfolder, exist_ok=True)

    # Open the PDF
    pdf = fitz.open(pdf_path)
    total_pages = pdf.page_count

    # Ensure split numbers are valid
    split_numbers = sorted(set(split_numbers)) # Remove duplicates and sort
    split_numbers = [s for s in split_numbers if 1 <= s <= total_pages] # Filter out-of-bounds
    

    ranges = []
    for i in range(len(split_numbers)):
        if i == len(split_numbers) - 1:
            # Last split number - create range from this number to end of PDF
            ranges.append((split_numbers[i] - 1, total_pages - 1))
        else:
            if i == 0 and split_numbers[0] == 1:
                # First page is a split point - handle it separately
                ranges.append((0, 0))
                if len(split_numbers) > 1:
                    # Add range from page 2 to next split point - 1
                    ranges.append((1, split_numbers[1] - 1))
            else:
                # Regular case - from current split point to next split point - 1
                start = split_numbers[i] - 1  # Convert to 0-based index
                end = split_numbers[i + 1] - 2  # -2 to not include next split point
                ranges.append((start, end))

    print("Debug - Page ranges to be created:", [(r[0]+1, r[1]+1) for r in ranges])

    for index, (start_page, end_page) in enumerate(ranges):
        writer = fitz.open()
        
        # Copy pages for this range
        for page_number in range(start_page, end_page + 1):
            writer.insert_pdf(pdf, from_page=page_number, to_page=page_number)
        
        # Skip empty writers
        if len(writer) == 0:
            print(f"Skipping empty split from {start_page + 1} to {end_page + 1}")
            writer.close()
            continue

        # Save temporary sub-document
        temp_filename = f"temp_split_{index + 1}.pdf"
        temp_path = os.path.join("temp", temp_filename)
        os.makedirs("temp", exist_ok=True)
        writer.save(temp_path)
        writer.close()

        # Extract text and rename
        text = extract_text_from_pdf(temp_path)
        voucher_number, date = extract_voucher_number_and_date(text)

        if voucher_number and date:
            date = date.replace("/", "-").replace(" ", "-")
            new_filename = f"{voucher_number}_{date}.pdf"
            new_file_path = os.path.join(success_subfolder, new_filename)
            try:
                shutil.move(temp_path, new_file_path)
                print(f"Split pages {start_page + 1}-{end_page + 1} -> '{new_filename}'")
            except Exception as e:
                print(f"Error moving file: {e}")
                # If moving fails, try to save to failure folder
                failure_path = os.path.join(failure_subfolder, temp_filename)
                shutil.move(temp_path, failure_path)
                print(f"Moved to failure folder due to error: {temp_filename}")
        else:
            # If renaming fails, move the original file to the failure subfolder
            new_file_path = os.path.join(failure_subfolder, f"{temp_filename}")
            shutil.move(temp_path, new_file_path)
            print(f"Failed to extract details from pages {start_page + 1}-{end_page + 1}")

        

    pdf.close()

    return success_subfolder, failure_subfolder