import io,json
from PIL import Image
import pytest
from pydantic import ValidationError
from app.core.config import Settings
from app.schemas.recognition import BoundingBox,PageRecognition
from app.services.recognition.pipeline import extract_json
from app.services.validation.files import detect_mime,validate_document
from app.services.tiling.tiles import make_tiles

def png(size=(100,100)):
 out=io.BytesIO();Image.new("RGB",size,"white").save(out,"PNG");return out.getvalue()
def test_magic_and_validation():
 assert detect_mime(png())=="image/png"; assert validate_document(png(),Settings())=="image/png"
def test_reject_unknown():
 with pytest.raises(Exception): detect_mime(b"hello")
def test_bbox_validation():
 assert BoundingBox(x1=0,y1=0,x2=1,y2=1)
 with pytest.raises(ValidationError): BoundingBox(x1=.5,y1=0,x2=.2,y2=1)
def test_json_safe_wrapper():
 assert extract_json('```json\n{"blocks": []}\n```')["blocks"]==[]
 with pytest.raises(ValueError): extract_json('{"blocks":[]} explanation')
def test_duplicate_ids_rejected():
 base={"page_number":1,"width":1,"height":1,"blocks":[{"id":"x","type":"paragraph","reading_order":1},{"id":"x","type":"paragraph","reading_order":2}]}
 with pytest.raises(ValidationError): PageRecognition.model_validate(base)
def test_tiles_overlap():
 tiles=make_tiles(png((2000,1000)),1000,100);assert len(tiles)==3;assert tiles[1].x==900
