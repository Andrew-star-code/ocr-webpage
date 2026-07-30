import io
from dataclasses import dataclass
import fitz
from PIL import Image, ImageOps
@dataclass
class RenderedPage:
    number:int; image:bytes; width:int; height:int; dpi:int; rotation:int; pdf_width:float|None=None; pdf_height:float|None=None
def _png(image: Image.Image)->bytes:
    out=io.BytesIO(); image.convert("RGB").save(out,"PNG",optimize=True); return out.getvalue()
def render_pages(data:bytes,mime:str,dpi:int)->list[RenderedPage]:
    pages=[]
    if mime=="application/pdf":
        with fitz.open(stream=data,filetype="pdf") as doc:
            for i,page in enumerate(doc):
                pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
                pages.append(RenderedPage(i+1,pix.tobytes("png"),pix.width,pix.height,dpi,page.rotation,page.rect.width,page.rect.height))
    else:
        with Image.open(io.BytesIO(data)) as source:
            for i in range(getattr(source,"n_frames",1)):
                source.seek(i); image=ImageOps.exif_transpose(source.copy()).convert("RGB")
                pages.append(RenderedPage(i+1,_png(image),image.width,image.height,dpi,0))
    return pages
