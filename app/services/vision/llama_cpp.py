import base64, httpx
from app.services.vision.base import BackendHealth, ModelInfo, VisionResponse
class LlamaCppVisionBackend:
    def __init__(self,base_url,model,timeout=600): self.base_url=base_url.rstrip("/"); self.model=model; self.client=httpx.AsyncClient(timeout=timeout)
    async def recognize_page(self,image,prompt,json_schema,options):
        data={"model":self.model,"messages":[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":"data:image/png;base64,"+base64.b64encode(image).decode()}}]}],"response_format":{"type":"json_schema","json_schema":{"name":"page","schema":json_schema}},"temperature":options.temperature,"seed":options.seed,"max_tokens":options.num_predict}
        r=await self.client.post(f"{self.base_url}/v1/chat/completions",json=data); r.raise_for_status(); body=r.json(); choice=body["choices"][0]
        return VisionResponse(choice["message"]["content"],choice.get("finish_reason"),body.get("usage",{}).get("prompt_tokens",0),body.get("usage",{}).get("completion_tokens",0))
    async def healthcheck(self):
        try: return BackendHealth((await self.client.get(f"{self.base_url}/health")).is_success,"llama.cpp")
        except httpx.HTTPError: return BackendHealth(False,"unreachable")
    async def get_model_info(self): return ModelInfo(self.model,True,True)
    async def warmup(self): await self.healthcheck()
