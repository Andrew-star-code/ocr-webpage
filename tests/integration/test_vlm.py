import io,json,os
from PIL import Image,ImageDraw
import pytest
from app.core.config import Settings
from app.services.vision.base import VisionRequestOptions
from app.services.vision.ollama import OllamaVisionBackend
@pytest.mark.vlm_integration
@pytest.mark.skipif(os.getenv("RUN_VLM_INTEGRATION")!="1",reason="requires RUN_VLM_INTEGRATION=1 and a local Ollama vision model")
@pytest.mark.asyncio
async def test_real_model_structured_recognition():
 image=Image.new("RGB",(420,120),"white");ImageDraw.Draw(image).text((20,35),"OCR TEST 123",fill="black");stream=io.BytesIO();image.save(stream,"PNG");s=Settings();model=os.getenv("OLLAMA_MODEL",s.ollama_model);backend=OllamaVisionBackend(os.getenv("OLLAMA_BASE_URL",s.ollama_base_url),model,120,10,-1,1,0)
 try:
  info=await backend.get_model_info(model)
  if not info.vision_capable:pytest.fail(f"Configured Ollama model {model} does not advertise Vision capability")
  schema={"type":"object","properties":{"text":{"type":"string"}},"required":["text"],"additionalProperties":False};response=await backend.recognize_page(stream.getvalue(),"Return exact visible text as structured JSON.",schema,VisionRequestOptions(model,num_predict=64,supports_json_schema=True));payload=json.loads(response.content);text=payload["text"].upper();assert "OCR" in text and "123" in text
 finally:await backend.close()
