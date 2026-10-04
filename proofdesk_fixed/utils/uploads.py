import os
import secrets
from PIL import Image
from werkzeug.utils import secure_filename

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}  # Pillow's canonical format names (covers jpg/jpeg)
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
from utils.paths import UPLOAD_DIR, MAX_UPLOAD_BYTES

MAX_FILE_SIZE = MAX_UPLOAD_BYTES  # 5 MB locally, 4 MB on Vercel (platform body limit)



class UploadError(Exception):
    pass


def validate_and_save(file_storage, subdir="records"):
    """
    Validates an uploaded image by actually decoding it with Pillow (does not
    trust the file extension or the browser-supplied Content-Type), enforces
    a size limit, and stores it under a random server-generated filename.
    Returns the relative path to store in the DB.
    """
    if file_storage is None or file_storage.filename == "":
        raise UploadError("No file was selected.")

    original_name = secure_filename(file_storage.filename)
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError("Unsupported file type. Allowed: JPG, JPEG, PNG, WEBP.")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size == 0:
        raise UploadError("Uploaded file is empty.")
    if size > MAX_FILE_SIZE:
        raise UploadError(f"File exceeds the {MAX_FILE_SIZE // (1024 * 1024)} MB size limit.")

    # Validate actual file content, not just extension/MIME header.
    try:
        img = Image.open(file_storage.stream)
        img.verify()
        real_format = img.format
    except Exception:
        raise UploadError("File is not a valid image.")

    if real_format not in ALLOWED_FORMATS:
        raise UploadError(f"Image content type '{real_format}' is not permitted.")

    file_storage.stream.seek(0)

    target_dir = os.path.join(UPLOAD_DIR, subdir)
    os.makedirs(target_dir, exist_ok=True)
    safe_name = f"{secrets.token_hex(16)}.{ext}"
    full_path = os.path.join(target_dir, safe_name)

    # Re-save via Pillow (re-encodes the pixel data) so no non-image payload
    # smuggled inside a polyglot file can survive; also strips EXIF/metadata.
    file_storage.stream.seek(0)
    img2 = Image.open(file_storage.stream)
    img2 = img2.convert("RGB") if real_format != "PNG" else img2.convert("RGBA")
    img2.save(full_path)

    return f"uploads/{subdir}/{safe_name}", real_format
