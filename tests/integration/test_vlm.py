import io,os
from PIL import Image,ImageDraw
import pytest
from app.core.config import Settings
from app.services.vision.base import VisionRequestOptions
from app.services.vision.ollama import OllamaVisionBackend
@pytest.mark.vlm_integration
@pytest.mark.skipif(os.getenv("RUN_VLM_INTEGRATION")!="1",reason="requires local Ollama model")
@pytest.mark.asyncio
async def test_real_model_recognizes_generated_image():
 image=Image.new("RGB",(320,100),"white");ImageDraw.Draw(image).text((20,30),"OCR TEST 123",fill="black");data=io.BytesIO();image.save(data,"PNG");s=Settings();backend=OllamaVisionBackend(os.getenv("OLLAMA_BASE_URL",s.ollama_base_url),os.getenv("OLLAMA_MODEL",s.ollama_model),120,10,-1,1,0)
 try:
  response=await backend.recognize_page(data.getvalue(),"Return JSON with non-empty text visible in the image.",{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]},VisionRequestOptions(os.getenv("OLLAMA_MODEL",s.ollama_model),num_predict=64));assert response.content.strip()
 finally:await backend.close()
