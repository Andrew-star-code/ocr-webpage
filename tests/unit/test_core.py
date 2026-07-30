import io
from PIL import Image
import pytest
from pydantic import ValidationError
from app.core.config import Settings
from app.core.exceptions import ServiceError
from app.schemas.recognition import BoundingBox,PageRecognition,ParagraphBlock
from app.services.recognition.pipeline import extract_json
from app.services.tiling.tiles import make_tiles,merge_pages,transform_page
from app.services.validation.files import detect_mime,validate_document

def png(size=(100,100)):
 out=io.BytesIO();Image.new("RGB",size,"white").save(out,"PNG");return out.getvalue()
def test_magic_validation_and_unknown():
 assert detect_mime(png())=="image/png";assert validate_document(png(),Settings())=="image/png"
 with pytest.raises(ServiceError):detect_mime(b"hello")
def test_bbox_and_unique_ids():
 with pytest.raises(ValidationError):BoundingBox(x1=.5,y1=0,x2=.2,y2=1)
 base={"page_number":1,"width":1,"height":1,"blocks":[{"id":"x","type":"paragraph","reading_order":1},{"id":"x","type":"paragraph","reading_order":2}]}
 with pytest.raises(ValidationError):PageRecognition.model_validate(base)
def test_json_wrapper_explanation_and_truncation():
 assert extract_json('```json\n{"blocks": []}\n```')["blocks"]==[]
 with pytest.raises(ServiceError):extract_json('{"blocks":[]} explanation')
 with pytest.raises(ServiceError,match="complete"):extract_json('{"blocks":[')
def test_tile_coordinates_and_overlap_aware_merge():
 tiles=make_tiles(png((2000,1000)),1000,100);assert len(tiles)==3 and tiles[1].x==900
 local=PageRecognition(page_number=1,width=1000,height=1000,blocks=[ParagraphBlock(id="a",reading_order=1,original_text="Длинный повторяющийся текст",bbox=BoundingBox(x1=.1,y1=.1,x2=.5,y2=.2))])
 transformed=transform_page(local,tiles[1]);assert transformed.blocks[0].bbox.x1==pytest.approx(.5)
 far=local.model_copy(update={"blocks":[local.blocks[0].model_copy(update={"id":"b","bbox":BoundingBox(x1=.6,y1=.6,x2=.9,y2=.7)})]})
 assert len(merge_pages(local,[far]).blocks)==2
