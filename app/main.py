from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .split_pdfs import router as split_pdfs_router
import os

uploads_path = os.path.join("app", "uploads")
os.makedirs(uploads_path, exist_ok=True)

app = FastAPI()

# Mount the static folder
app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")

# Enable CORS from all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow requests from all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# Include router for PDF Splitter
app.include_router(split_pdfs_router, prefix="/pdf_splitter", tags=["PDF Splitter"])
