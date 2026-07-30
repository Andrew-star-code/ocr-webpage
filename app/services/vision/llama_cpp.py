import base64, httpx
from app.services.vision.base import BackendHealth, ModelInfo, VisionResponse
class LlamaCppVisionBackend:
    name="llama_cpp"
    def __init__(self,base_url,model,timeout=600,client=None): self.base_url=base_url.rstrip("/");self.default_model=model;self.client=client or httpx.AsyncClient(timeout=timeout)
    async def recognize_page(self,image,prompt,json_schema,options):
        content=[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":"data:image/png;base64,"+base64.b64encode(image).decode("ascii")}}]
        messages=([{"role":"system","content":options.system_prompt}] if options.system_prompt else [])+[{"role":"user","content":content}]
        data={"model":options.model or self.default_model,"messages":messages,"temperature":options.temperature,"seed":options.seed,"max_tokens":options.num_predict}
        if options.supports_json_schema:data["response_format"]={"type":"json_schema","json_schema":{"name":"page","schema":json_schema}}
        r=await self.client.post(f"{self.base_url}/v1/chat/completions",json=data);r.raise_for_status();body=r.json();choice=body["choices"][0]
        return VisionResponse(choice["message"]["content"],choice.get("finish_reason"),body.get("usage",{}).get("prompt_tokens",0),body.get("usage",{}).get("completion_tokens",0))
    async def healthcheck(self):
        try:return BackendHealth((await self.client.get(f"{self.base_url}/health")).is_success,"llama.cpp")
        except httpx.HTTPError:return BackendHealth(False,"unreachable")
    async def get_model_info(self,model=None):return ModelInfo(model or self.default_model,True,True)
    async def warmup(self):await self.healthcheck()
    async def close(self):await self.client.aclose()
