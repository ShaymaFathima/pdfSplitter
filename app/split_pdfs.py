from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from .utils import *
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor, as_completed
import uuid
import aiofiles
import asyncio
from typing import List

router = APIRouter()

UPLOAD_FOLDER = "app/uploads"
@router.post("/upload_pdf")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    results = []
    file_paths = []
    try:
        # Ensure upload folder exists
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        # Save files concurrently
        async def save_and_process_file(file):
            file_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}_{file.filename}")
            await save_file(file, file_path)
            return file_path
        # Use asyncio to save files concurrently
        file_paths = await asyncio.gather(*[save_and_process_file(file) for file in files])
        # Use multiprocessing for CPU-bound PDF processing
        with ProcessPoolExecutor(max_workers=min(len(files), os.cpu_count())) as executor:
            # Use concurrent.futures to process PDFs
            page_futures = [
                executor.submit(preprocess_file, file_path) 
                for file_path in file_paths
            ]          
            # Wait for all futures to complete
            splitting_page_numbers = [future.result() for future in as_completed(page_futures)]
        # Prepare response
        results = [
            {
                "original_filename": os.path.basename(file_path),
                "pdf_path": file_path.replace("app/", ""),
                "split_numbers": pages
            }
            for file_path, pages in zip(file_paths, splitting_page_numbers)
        ]
        return {"uploaded_pdfs": results}
    except Exception as e:
        # Cleanup uploaded files in case of error
        for file_path in file_paths:
            try:
                os.remove(file_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Error uploading files: {e}")



@router.post("/split_pdfs")
async def split_pdfs_endpoint(pdf_details: List[dict]):
    try:
        result = await asyncio.to_thread(split_and_save_pdfs, pdf_details)
        return {"timestamp": result["timestamp"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/split_pdfs/timestamps")
async def get_split_timestamps():
    base_split_dir = os.path.join("app", "uploads", "split")
    timestamps = list_folders(base_split_dir)
    if not timestamps:
        raise HTTPException(status_code=404, detail="No split folders found.")
    return {"timestamps": timestamps}




# GET API to list all sub-documents within a timestamped folder
@router.get("/split_pdfs/timestamps/{timestamp}")
async def get_split_files_by_timestamp(timestamp: str):
    base_split_dir = os.path.join("app", "uploads", "split")
    split_folder = os.path.join(base_split_dir, timestamp)
    if not os.path.exists(split_folder):
        raise HTTPException(status_code=404, detail=f"Timestamp folder not found: {timestamp}") 
    files = [f"uploads/split/{timestamp}/{file}" for file in os.listdir(split_folder) if file.endswith(".pdf")]
    return {"files": files}



@router.post("/rename_all")
async def rename_all(folder_name: str = Query(..., description="Timestamped folder name in uploads/split")):
    """
    Rename all files in a specified timestamped folder.
    Move renamed files to 'rename_after_split', organized into 'success' and 'failure'.
    """
    try:
        # Define source and target paths
        source_folder = os.path.join("app", "uploads", "split", folder_name)
        target_base = os.path.join("app", "uploads", "rename_after_split")
        target_folder = os.path.join(target_base, folder_name)
        # Check if source folder exists
        if not os.path.exists(source_folder):
            raise HTTPException(status_code=404, detail="Specified folder does not exist.")
        # Create target folder and subfolders for success and failure
        if not os.path.exists(target_folder):
            os.makedirs(target_folder)
        success_folder, failure_folder = create_subfolders(target_folder)
        # Process files in the source folder
        renamed_files, failed_files = handle_files_in_folder(source_folder, success_folder, failure_folder)
        # Remove the original source folder after moving files
        os.chmod(source_folder, 0o777)  # Ensure folder is writable
        os.rmdir(source_folder)
        # Return response with moved folder path
        return {
            "message": "Renaming completed."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during renaming: {str(e)}")



@router.get("/rename_all/timestamps")
async def get_split_timestamps():
    base_split_dir = os.path.join("app", "uploads", "rename_after_split")
    timestamps = list_folders(base_split_dir)
    if not timestamps:
        raise HTTPException(status_code=404, detail="No folders found.")
    return {"timestamps": timestamps}



@router.get("/rename_all/timestamps/{timestamp}/{folder_type}")
async def rename_all(timestamp: str, folder_type: str):
    """
    Get all files in the success or failure folder under a timestamped subfolder.
    """
    if folder_type not in ["success", "failure"]:
        raise HTTPException(status_code=400, detail="Invalid folder type. Must be 'success' or 'failure'.")
    base_path = os.path.join("app/uploads/rename_after_split", timestamp, folder_type)
    if not os.path.exists(base_path):
        raise HTTPException(status_code=404, detail="Specified folder does not exist.")
    files =  [f"uploads/rename_after_split/{timestamp}/{folder_type}/{file}" 
             for file in os.listdir(base_path)]
    if not files:
        raise HTTPException(status_code=404, detail="No files found in the specified folder.")
    return {
        "folder": f"/uploads/rename_after_split/{timestamp}/{folder_type}",
        "files": files
    }



@router.post("/upload_and_rename")
async def upload_and_rename_files(files: List[UploadFile]):
    """
    Upload and rename files, creating timestamped subfolders inside 'app/uploads/rename_without_split'.
    """
    try:
        base_folder = os.path.join("app", "uploads", "rename_without_split")
        os.makedirs(base_folder, exist_ok=True)
        # Create timestamped folder manually within the API
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        timestamped_folder = os.path.join(base_folder, timestamp)
        os.makedirs(timestamped_folder, exist_ok=True)
        # Create success and failure subfolders within the timestamped folder
        success_folder, failure_folder = create_subfolders(timestamped_folder)
        # Save uploaded files to a temporary folder
        temp_folder = "temp"
        os.makedirs(temp_folder, exist_ok=True)
        for file in files:
            temp_path = os.path.join(temp_folder, file.filename)
            with open(temp_path, "wb") as temp_file:
                temp_file.write(await file.read())
        # Use handle_files_in_folder to process files
        renamed_files, failed_files = handle_files_in_folder(temp_folder, success_folder, failure_folder)
        # Clean up temporary folder after processing
        shutil.rmtree(temp_folder, ignore_errors=True)
        return {
            "timestamp": timestamp
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during upload and rename: {str(e)}")



@router.get("/upload_and_rename/timestamps")
async def get_split_timestamps():
    base_split_dir = os.path.join("app", "uploads", "rename_without_split")
    timestamps = list_folders(base_split_dir)
    if not timestamps:
        raise HTTPException(status_code=404, detail="No folders found.")
    return {"timestamps": timestamps}



@router.get("/upload_and_rename/timestamps/{timestamp}/{folder_type}")
async def rename_all(timestamp: str, folder_type: str):
    """
    Get all files in the success or failure folder under a timestamped subfolder.
    """
    if folder_type not in ["success", "failure"]:
        raise HTTPException(status_code=400, detail="Invalid folder type. Must be 'success' or 'failure'.")
    base_path = os.path.join("app/uploads/rename_without_split", timestamp, folder_type)
    if not os.path.exists(base_path):
        raise HTTPException(status_code=404, detail="Specified folder does not exist.")
    files =  [f"uploads/rename_without_split/{timestamp}/{folder_type}/{file}" 
             for file in os.listdir(base_path)]
    if not files:
        raise HTTPException(status_code=404, detail="No files found in the specified folder.")
    return {
        "folder": f"/uploads/rename_without_split/{timestamp}/{folder_type}",
        "files": files
    }