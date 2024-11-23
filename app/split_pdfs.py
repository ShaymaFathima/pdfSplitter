from fastapi import APIRouter, UploadFile, File, HTTPException
from .utils import *
import shutil
from typing import List

router = APIRouter()

UPLOAD_FOLDER = "app/uploads"
SUCCESS_FOLDER = os.path.join(UPLOAD_FOLDER, "success")
FAILURE_FOLDER = os.path.join(UPLOAD_FOLDER, "failure")
os.makedirs(SUCCESS_FOLDER, exist_ok=True)
os.makedirs(FAILURE_FOLDER, exist_ok=True)

@router.post("/upload_pdf")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    cheque, bank_advice, staff_form = load_templates()
    target_width, target_height = get_pdf_page_size(file_path)
    cheque_resized = resize_image(cheque, target_width, target_height)
    bank_advice_resized = resize_image(bank_advice, target_width, target_height)
    staff_form_resized = resize_image(staff_form, target_width, target_height)
    logo_templates = {
        "Cheque": [cheque_resized],
        "Internal Bank Advice": [bank_advice_resized],
        "Staff Form": [staff_form_resized]
    }
    
    splitting_page_numbers = find_splitting_page_numbers(file_path, logo_templates)
    return {"pdf_path": file_path, "splitting_page_numbers": splitting_page_numbers}


@router.post("/split_and_rename")
async def split_and_rename(pdf_path: str, split_page_list: List[int]):
    """
    Splits and renames a PDF based on voucher number and date.
    """
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found.")
    print(pdf_path)

    # Split and rename the PDF
    success_subfolder, failure_subfolder = split_and_rename_pdfs(
        pdf_path=pdf_path,
        split_numbers=split_page_list,
        success_folder=SUCCESS_FOLDER,
        failure_folder=FAILURE_FOLDER,
    )
    
    return {
        "success_folder": success_subfolder,
        "failure_folder": failure_subfolder,
    }


@router.get("/list_folders")
async def list_success_failure_folders():
    """
    Lists timestamped folders under success and failure directories.
    """
    success_folders = list_folders(SUCCESS_FOLDER)
    failure_folders = list_folders(FAILURE_FOLDER)
    
    return {
        "success_folders": success_folders,
        "failure_folders": failure_folders,
    }


@router.get("/get_split_files/{folder_type}/{timestamp}")
async def get_split_files(folder_type: str, timestamp: str):
    """
    Retrieves split files from a given timestamped folder.
    """
    if folder_type not in ["success", "failure"]:
        raise HTTPException(status_code=400, detail="Invalid folder type. Must be 'success' or 'failure'.")
    
    base_folder = SUCCESS_FOLDER if folder_type == "success" else FAILURE_FOLDER
    physical_path = os.path.join("app/uploads", folder_type, timestamp)
    
    # List files in the target folder
    files = [f"/uploads/{folder_type}/{timestamp}/{file}" 
             for file in os.listdir(physical_path)]
    
    return {
        "folder": f"/uploads/{folder_type}/{timestamp}",
        "files": files
    }

