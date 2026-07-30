import asyncio, base64
import httpx
from app.core.exceptions import ServiceError
from app.services.vision.base import BackendHealth, ModelInfo, VisionRequestOptions, VisionResponse
class OllamaVisionBackend:
    def __init__(self, base_url: str, model: str, timeout: float=600, connect_timeout: float=10, keep_alive: int=-1, concurrency: int=1):
        self.base_url=base_url.rstrip("/"); self.model=model; self.keep_alive=keep_alive; self.sem=asyncio.Semaphore(concurrency)
        self.client=httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=connect_timeout))
    async def recognize_page(self,image,prompt,json_schema,options):
        payload={"model":self.model,"messages":[{"role":"user","content":prompt,"images":[base64.b64encode(image).decode()]}],"format":json_schema,"stream":False,"keep_alive":self.keep_alive,"options":{"temperature":options.temperature,"seed":options.seed,"num_ctx":options.num_ctx,"num_predict":options.num_predict}}
        try:
            async with self.sem: response=await self.client.post(f"{self.base_url}/api/chat",json=payload)
            response.raise_for_status(); data=response.json()
        except httpx.TimeoutException as exc: raise ServiceError("vision_request_timeout","Vision request timed out",504) from exc
        except (httpx.HTTPError, ValueError) as exc: raise ServiceError("ollama_unavailable","Ollama is unavailable",503) from exc
        return VisionResponse(data.get("message",{}).get("content",""),data.get("done_reason"),data.get("prompt_eval_count",0),data.get("eval_count",0))
    async def healthcheck(self):
        try: return BackendHealth((await self.client.get(f"{self.base_url}/api/tags")).is_success,"ollama")
        except httpx.HTTPError: return BackendHealth(False,"unreachable")
    async def get_model_info(self):
        response=await self.client.post(f"{self.base_url}/api/show",json={"model":self.model})
        if response.status_code==404: raise ServiceError("model_not_found","Configured model is not installed",503)
        response.raise_for_status(); capabilities=response.json().get("capabilities",[])
        return ModelInfo(self.model,"vision" in capabilities,True)
    async def warmup(self): await self.get_model_info()
