import io
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.recognition import *
from app.services.recognition.pipeline import RecognitionResult
from app.services.rendering.pages import RenderedPage

def fixture_result():
 stream=io.BytesIO();Image.new("RGB",(200,100),"white").save(stream,"PNG");image=stream.getvalue();page=PageRecognition(page_number=1,width=200,height=100,blocks=[ParagraphBlock(id="p",reading_order=1,original_text="Тест",bbox=BoundingBox(x1=.1,y1=.1,x2=.9,y2=.3))]);doc=DocumentRecognition(document_id="d",pages=[page],original_text="Тест",metadata=ProcessingMetadata(backend="ollama",model_profile="default",model_name="m"));return RecognitionResult(doc,[image],[RenderedPage(1,image,200,100,300,0,200,100)])
class Allow:
 async def check(self,request):return None
 async def close(self):return None
class Pipeline:
 async def run(self,*args,**kwargs):return fixture_result()
def upload():
 stream=io.BytesIO();Image.new("RGB",(20,20),"white").save(stream,"PNG");return {"file":("unsafe/../../x.png",stream.getvalue(),"image/png")}
def test_json_flags_and_api_key():
 with TestClient(app) as client:
  app.state.pipeline=Pipeline();app.state.rate_limiter=Allow();denied=client.post("/v1/ocr",files=upload());assert denied.status_code==401
  response=client.post("/v1/ocr",headers={"X-API-Key":"change-me"},files=upload(),data={"output_format":"json","include_bounding_boxes":"false","include_processing_metadata":"false"});assert response.status_code==200;body=response.json();assert "metadata" not in body and "bbox" not in body["pages"][0]["blocks"][0]
def test_docx_searchable_pdf_and_validation():
 with TestClient(app) as client:
  app.state.pipeline=Pipeline();app.state.rate_limiter=Allow();headers={"X-API-Key":"change-me"}
  assert client.post("/v1/ocr",headers=headers,files=upload(),data={"output_format":"docx"}).content.startswith(b"PK")
  pdf=client.post("/v1/ocr",headers=headers,files=upload(),data={"output_format":"searchable_pdf"});assert pdf.status_code==200 and pdf.content.startswith(b"%PDF")
  assert client.post("/v1/ocr",headers=headers,files=upload(),data={"output_format":"bad"}).status_code==400
  unknown=client.post("/v1/ocr",headers=headers,files=upload(),data={"model_profile":"missing"});assert unknown.status_code==404 and unknown.json()["error"]["code"]=="model_profile_not_found"
def test_profiles_endpoint_is_loaded_registry():
 with TestClient(app) as client:
  app.state.rate_limiter=Allow();response=client.get("/v1/model/profiles",headers={"X-API-Key":"change-me"});assert response.status_code==200;names={p["name"] for p in response.json()["profiles"]};assert "default" in names and "system_prompt" not in response.text
