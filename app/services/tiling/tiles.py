import io
from dataclasses import dataclass
from PIL import Image
from app.schemas.recognition import PageRecognition
@dataclass
class Tile: id:str; image:bytes; x:int; y:int; width:int; height:int; page_width:int; page_height:int
def make_tiles(data:bytes,size:int=1600,overlap:int=160)->list[Tile]:
    image=Image.open(io.BytesIO(data)); result=[]
    for y in range(0,image.height,max(1,size-overlap)):
        for x in range(0,image.width,max(1,size-overlap)):
            x2=min(x+size,image.width); y2=min(y+size,image.height); out=io.BytesIO(); image.crop((x,y,x2,y2)).save(out,"PNG")
            result.append(Tile(f"tile-{len(result)+1}",out.getvalue(),x,y,x2-x,y2-y,image.width,image.height))
            if x2==image.width: break
        if y2==image.height: break
    return result
def merge_pages(base:PageRecognition,partials:list[PageRecognition])->PageRecognition:
    blocks=list(base.blocks)
    for page in partials:
        for candidate in page.blocks:
            duplicate=any(candidate.original_text and candidate.original_text==b.original_text for b in blocks)
            if not duplicate: blocks.append(candidate)
    for index,block in enumerate(sorted(blocks,key=lambda b:(b.bbox.y1 if b.bbox else 1,b.bbox.x1 if b.bbox else 0)),1): block.reading_order=index
    return base.model_copy(update={"blocks":blocks})
