import os
from fastapi import UploadFile
from pathlib import Path

# Define the upload directory relative to the project root
#UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../uploads"))
UPLOAD_DIR = Path(__file__).resolve().parent.parent
os.makedirs(UPLOAD_DIR, exist_ok=True)

def save_upload_file_tmp(upload_file: UploadFile) -> str:
    """
    Save the uploaded file to the persistent uploads directory using its original filename.
    Returns the absolute file path.
    """
    file_path = os.path.join(UPLOAD_DIR, upload_file.filename)
    print(file_path)
    with open(file_path, "wb") as f:
        f.write(upload_file.file.read())
    return file_path

# def get_all_uploaded_files() -> dict:
#     """
#     Returns a dictionary of all uploaded PDF/DOCX files in the uploads directory.
#     Format: {filename: full_path}
#     """
#     files = {}
#     for f in os.listdir(UPLOAD_DIR):
#         if f.endswith((".pdf", ".docx")):
#             files[f] = os.path.join(UPLOAD_DIR, f)
#     return files
