import io
import fitz
from PIL import Image, ImageFile, UnidentifiedImageError
from app.core.config import Settings
from app.core.exceptions import ServiceError
ImageFile.LOAD_TRUNCATED_IMAGES=False
MAGIC={b"%PDF-":"application/pdf",b"\x89PNG\r\n\x1a\n":"image/png",b"\xff\xd8\xff":"image/jpeg",b"II*\x00":"image/tiff",b"MM\x00*":"image/tiff",b"RIFF":"image/webp"}
def detect_mime(data: bytes)->str:
    for signature,mime in MAGIC.items():
        if data.startswith(signature):
            if mime=="image/webp" and data[8:12]!=b"WEBP": break
            return mime
    raise ServiceError("unsupported_file_type","Unsupported file type",415)
def validate_document(data: bytes,settings: Settings)->str:
    if not data: raise ServiceError("invalid_document","Empty document")
    if len(data)>settings.max_upload_size: raise ServiceError("file_too_large","Upload exceeds configured limit",413)
    mime=detect_mime(data)
    if mime=="application/pdf":
        try:
            doc=fitz.open(stream=data,filetype="pdf")
            if doc.needs_pass: raise ServiceError("encrypted_pdf","Encrypted PDF is not supported")
            if doc.page_count>settings.max_pages: raise ServiceError("too_many_pages","Document has too many pages")
            if doc.page_count==0: raise ServiceError("invalid_document","PDF contains no pages")
        except ServiceError: raise
        except Exception as exc: raise ServiceError("invalid_document","Damaged PDF") from exc
    else:
        try:
            Image.MAX_IMAGE_PIXELS=settings.max_image_pixels
            with Image.open(io.BytesIO(data)) as image:
                frames=getattr(image,"n_frames",1)
                if frames>settings.max_pages: raise ServiceError("too_many_pages","Image has too many frames")
                image.verify()
        except ServiceError: raise
        except (UnidentifiedImageError,Image.DecompressionBombError,OSError) as exc: raise ServiceError("invalid_document","Damaged or unsafe image") from exc
    return mime
