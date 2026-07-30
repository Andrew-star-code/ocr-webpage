import asyncio,json,re,time,uuid
from pydantic import ValidationError
from app.core.metrics import PAGES,VISION_REQUESTS,VISION_RETRIES
from app.schemas.recognition import DocumentRecognition,PageRecognition,ProcessingMetadata
from app.services.preprocessing.images import preprocess
from app.services.rendering.pages import render_pages
from app.services.validation.files import validate_document
from app.services.vision.base import VisionRequestOptions
PROMPT="""Точно перепиши только видимое. Не исправляй орфографию, пунктуацию, регистр, числа, даты, суммы, имена, реквизиты и формулировки. Не дополняй текст по смыслу, строки или ячейки. Не объединяй колонки. Неразличимое: [НЕРАЗБОРЧИВО]. Обрезанное: [ФРАГМЕНТ ОБРЕЗАН]. Верни только JSON по схеме, без Markdown и пояснений. Координаты нормализованы 0..1. Язык: {language}. Таблицы: {tables}. Страница: {page}."""
def extract_json(text:str)->dict:
    value=text.strip(); match=re.fullmatch(r"```(?:json)?\s*(.*?)\s*```",value,re.S)
    if match: value=match.group(1)
    decoder=json.JSONDecoder()
    for i,ch in enumerate(value):
        if ch in "{[":
            try:
                obj,end=decoder.raw_decode(value[i:])
                if value[i+end:].strip(): raise ValueError("extraneous model explanation")
                return obj
            except json.JSONDecodeError: continue
    raise ValueError("model output is not complete JSON")
class RecognitionPipeline:
    def __init__(self,settings,backend): self.s=settings; self.backend=backend; self.document_sem=asyncio.Semaphore(settings.max_active_documents)
    async def run(self,data,language="rus+eng",profile="default",preprocess_mode="auto",normalize=False,detect_tables=True,dpi=300,allow_partial=False):
        async with self.document_sem:
            started=time.monotonic(); mime=validate_document(data,self.s); rendered=render_pages(data,mime,dpi); pages=[]; retries=0; prep=[]
            for source in rendered:
                processed,info=preprocess(source.image,preprocess_mode); prep.append(info)
                schema=PageRecognition.model_json_schema(); prompt=PROMPT.format(language=language,tables=detect_tables,page=source.number)
                error=None
                for attempt in range(self.s.max_vision_retries+1):
                    try:
                        VISION_REQUESTS.labels(self.s.vision_backend).inc(); response=await asyncio.wait_for(self.backend.recognize_page(processed,prompt,schema,VisionRequestOptions(self.s.ollama_temperature,self.s.ollama_seed,self.s.ollama_num_ctx,self.s.ollama_num_predict)),self.s.page_processing_timeout)
                        if response.done_reason in {"length","max_tokens"}: raise ValueError("output truncated")
                        payload=extract_json(response.content); payload.update({"page_number":source.number,"width":source.width,"height":source.height,"rotation":source.rotation})
                        page=PageRecognition.model_validate(payload)
                        if not page.blocks: raise ValueError("empty recognition")
                        pages.append(page); PAGES.inc(); break
                    except (ValueError,ValidationError) as exc:
                        error=exc; retries+=1; VISION_RETRIES.labels("invalid_response").inc()
                        if attempt<self.s.max_vision_retries: await asyncio.sleep(min(2**attempt,8))
                else:
                    if not allow_partial: raise ValueError(f"page {source.number}: invalid model response") from error
            original="\n\n".join(b.original_text for p in pages for b in sorted(p.blocks,key=lambda x:x.reading_order) if b.original_text)
            normalized=re.sub(r"[ \t]+"," ",original).replace("-\n","") if normalize else None
            model=self.s.ollama_model if self.s.vision_backend=="ollama" else self.s.llama_cpp_model
            meta=ProcessingMetadata(backend=self.s.vision_backend,model_profile=profile,model_name=model,retries=retries,durations_ms={"total":(time.monotonic()-started)*1000},preprocessing={"pages":prep})
            return DocumentRecognition(document_id=str(uuid.uuid4()),pages=pages,original_text=original,normalized_text=normalized,metadata=meta,partial=len(pages)!=len(rendered))
