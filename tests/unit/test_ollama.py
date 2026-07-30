import json
import httpx,pytest
from app.core.exceptions import ServiceError
from app.services.vision.base import VisionRequestOptions
from app.services.vision.ollama import OllamaVisionBackend
@pytest.mark.asyncio
async def test_retry_429_and_profile_model(monkeypatch):
 calls=[]
 async def handler(request):
  calls.append(json.loads(request.content));return httpx.Response(429,headers={"Retry-After":"0"}) if len(calls)==1 else httpx.Response(200,json={"message":{"content":"{}"}})
 client=httpx.AsyncClient(transport=httpx.MockTransport(handler));backend=OllamaVisionBackend("http://local","default",client=client,max_retries=1)
 monkeypatch.setattr("asyncio.sleep",lambda _: _immediate())
 response=await backend.recognize_page(b"x","prompt",{},VisionRequestOptions("profile-model","system"));assert response.content=="{}" and calls[0]["model"]=="profile-model" and calls[0]["messages"][0]["content"]=="system";await backend.close()
@pytest.mark.asyncio
async def test_nonretryable_400():
 client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(400)));backend=OllamaVisionBackend("http://local","m",client=client,max_retries=2)
 with pytest.raises(ServiceError) as error:await backend.recognize_page(b"x","p",{},VisionRequestOptions("m"))
 assert error.value.code=="vision_inference_failed";await backend.close()
async def _immediate():return None
@pytest.mark.asyncio
async def test_read_timeout_is_retried(monkeypatch):
 calls=0
 async def handler(request):
  nonlocal calls;calls+=1
  if calls==1:raise httpx.ReadTimeout("slow",request=request)
  return httpx.Response(200,json={"message":{"content":"{}"}})
 client=httpx.AsyncClient(transport=httpx.MockTransport(handler));backend=OllamaVisionBackend("http://local","m",client=client,max_retries=1);monkeypatch.setattr("asyncio.sleep",lambda _: _immediate());assert (await backend.recognize_page(b"x","p",{},VisionRequestOptions("m"))).content=="{}";assert calls==2;await backend.close()
@pytest.mark.asyncio
async def test_empty_response_is_retried(monkeypatch):
 calls=0
 async def handler(request):
  nonlocal calls;calls+=1;return httpx.Response(200,json={"message":{"content":"" if calls==1 else "{}"}})
 client=httpx.AsyncClient(transport=httpx.MockTransport(handler));backend=OllamaVisionBackend("http://local","m",client=client,max_retries=1);monkeypatch.setattr("asyncio.sleep",lambda _: _immediate());assert (await backend.recognize_page(b"x","p",{},VisionRequestOptions("m"))).content=="{}";await backend.close()
