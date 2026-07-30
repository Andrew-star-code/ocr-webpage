import asyncio,io,json,re,time,uuid
from dataclasses import dataclass
from typing import Awaitable,Callable
from PIL import Image
from pydantic import ValidationError
from app.core.exceptions import ServiceError
from app.core.metrics import PAGES,VISION_REQUESTS,VISION_RETRIES
from app.schemas.recognition import DocumentRecognition,PageRecognition,ProcessingMetadata,TableBlock
from app.services.preprocessing.images import preprocess
from app.services.rendering.pages import RenderedPage,render_pages
from app.services.tiling.tiles import make_tiles,merge_pages,transform_bbox,transform_page
from app.services.validation.files import validate_document
from app.services.vision.base import VisionRequestOptions

_BLANK_IMAGE=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
ProgressCallback=Callable[[str,int,int,int],Awaitable[None]]
CancelCallback=Callable[[],Awaitable[bool]]
@dataclass(slots=True)
class RecognitionResult:
    document:DocumentRecognition
    page_images:list[bytes]
    rendered_pages:list[RenderedPage]

def extract_json(text,response_cleanup="safe_wrappers"):
    value=text.strip()
    if not value:raise ServiceError("invalid_model_response","Model returned an empty response",502)
    if response_cleanup=="safe_wrappers":
        match=re.fullmatch(r"```(?:json)?\s*(.*?)\s*```",value,re.S)
        if match:value=match.group(1)
    decoder=json.JSONDecoder()
    for index,char in enumerate(value):
        if char in "{[":
            try:
                obj,end=decoder.raw_decode(value[index:])
                if value[index+end:].strip():raise ServiceError("invalid_model_response","Model added text outside JSON",502)
                return obj
            except json.JSONDecodeError:continue
    code="output_truncated" if value.count("{")>value.count("}") else "invalid_model_response"
    raise ServiceError(code,"Model output is not complete JSON",502)
class RecognitionPipeline:
    def __init__(self,settings,backends,profiles):self.s=settings;self.backends=backends;self.profiles=profiles;self.document_sem=asyncio.Semaphore(settings.max_active_documents)
    async def _cancelled(self,cancel):
        if cancel and await cancel():raise ServiceError("processing_cancelled","Processing cancelled",409)
    def _options(self,profile):
        return VisionRequestOptions(profile.model,profile.system_prompt,self.s.ollama_temperature,self.s.ollama_seed,profile.num_ctx,profile.num_predict,profile.supports_json_schema)
    async def _recognize(self,image,page_number,width,height,profile,prompt,cancel):
        backend=self.backends.get(profile.backend);schema=PageRecognition.model_json_schema();last=None
        for attempt in range(self.s.max_vision_retries+1):
            await self._cancelled(cancel)
            try:
                request_prompt=prompt if attempt==0 else prompt+f" Повтор: {profile.retry_mode}. Исправь только структуру JSON, не меняй распознанный текст."
                VISION_REQUESTS.labels(profile.backend).inc();response=await asyncio.wait_for(backend.recognize_page(image,request_prompt,schema,self._options(profile)),self.s.page_processing_timeout)
                if response.done_reason in {"length","max_tokens"}:raise ServiceError("output_truncated","Model output was truncated",502)
                if profile.two_stage:
                    normalization_prompt="Преобразуй следующий локально распознанный результат в переданную JSON Schema. Не исправляй и не изменяй текст: "+response.content
                    response=await asyncio.wait_for(backend.recognize_page(_BLANK_IMAGE,normalization_prompt,schema,self._options(profile)),self.s.page_processing_timeout)
                payload=extract_json(response.content,profile.response_cleanup);payload.update(page_number=page_number,width=width,height=height)
                page=PageRecognition.model_validate(payload)
                if not page.blocks:raise ServiceError("invalid_model_response","Recognized page is empty",502)
                return page,attempt
            except ValidationError as exc:last=ServiceError("schema_validation_failed","Model response failed schema validation",502,{"errors":len(exc.errors())})
            except ServiceError as exc:
                last=exc
                if exc.code not in {"invalid_model_response","schema_validation_failed","output_truncated"}:raise
            if attempt<self.s.max_vision_retries:
                VISION_RETRIES.labels(last.code).inc();await asyncio.sleep(min(.5*2**attempt,4))
        raise last or ServiceError("invalid_model_response","Invalid model response",502)
    def _prompt(self,profile,language,tables,page,mode="page"):
        return profile.user_prompt.format(language=language,tables=str(tables and profile.supports_tables).lower(),page=page,mode=mode)
    async def _table_crops(self,page,image,profile,cancel):
        source=Image.open(io.BytesIO(image));changed=[]
        for block in page.blocks:
            complex_table=isinstance(block,TableBlock) and block.bbox and (block.warnings or (block.bbox.x2-block.bbox.x1)*(block.bbox.y2-block.bbox.y1)>.45)
            if not complex_table:changed.append(block);continue
            box=block.bbox;pixel=(int(box.x1*source.width),int(box.y1*source.height),int(box.x2*source.width),int(box.y2*source.height));out=io.BytesIO();source.crop(pixel).save(out,"PNG")
            prompt=self._prompt(profile,"rus+eng",True,page.page_number,"table_only")+" Верни ровно одну таблицу; не создавай невидимые ячейки."
            refined,_=await self._recognize(out.getvalue(),page.page_number,pixel[2]-pixel[0],pixel[3]-pixel[1],profile,prompt,cancel)
            tables=[b for b in refined.blocks if isinstance(b,TableBlock)]
            if tables:
                tile=type("Crop",(),{"x":pixel[0],"y":pixel[1],"width":pixel[2]-pixel[0],"height":pixel[3]-pixel[1],"page_width":source.width,"page_height":source.height})
                replacement=tables[0].model_copy(update={"id":block.id,"reading_order":block.reading_order,"bbox":transform_bbox(tables[0].bbox,tile) if tables[0].bbox else box})
                changed.append(replacement)
            else:changed.append(block)
        return page.model_copy(update={"blocks":changed})
    async def run(self,data,language="rus+eng",profile_name="default",preprocess_mode="auto",normalize=False,detect_tables=True,dpi=300,allow_partial=False,progress=None,cancel=None):
        profile=self.profiles.get(profile_name)
        if profile.backend not in self.backends.backends:raise ServiceError("invalid_request","Profile backend is unavailable",400)
        async with self.document_sem:
            started=time.monotonic();mime=validate_document(data,self.s);rendered=render_pages(data,mime,dpi);pages=[];retries=0;prep=[];tiles_meta=[];images=[]
            if progress:await progress("rendering",0,len(rendered),0)
            for source in rendered:
                await self._cancelled(cancel);processed,info=preprocess(source.image,preprocess_mode);prep.append(info);images.append(source.image)
                strategy=profile.tiling_strategy
                oversized=source.width*source.height>profile.max_image_size or max(source.width,source.height)>profile.recommended_resolution
                if strategy!="full_page" and not oversized:strategy="full_page"
                base=PageRecognition(page_number=source.number,width=source.width,height=source.height,blocks=[]);page_retries=0
                if strategy in {"full_page","full_page_plus_tiles"}:
                    base,page_retries=await self._recognize(processed,source.number,source.width,source.height,profile,self._prompt(profile,language,detect_tables,source.number),cancel)
                if strategy in {"tiles","full_page_plus_tiles"}:
                    partials=[]
                    for tile in make_tiles(processed,profile.tile_size,profile.tile_overlap):
                        local,count=await self._recognize(tile.image,source.number,tile.width,tile.height,profile,self._prompt(profile,language,detect_tables,source.number,"tile"),cancel)
                        partials.append(transform_page(local,tile));page_retries+=count;tiles_meta.append({"page":source.number,"id":tile.id,"x":tile.x,"y":tile.y,"width":tile.width,"height":tile.height})
                    base=merge_pages(base,partials)
                if detect_tables and profile.supports_tables:base=await self._table_crops(base,processed,profile,cancel)
                pages.append(base);retries+=page_retries;PAGES.inc()
                if progress:await progress("recognizing",source.number,len(rendered),retries)
            original="\n\n".join(b.original_text for p in pages for b in sorted(p.blocks,key=lambda x:x.reading_order) if b.original_text);normalized=re.sub(r"[ \t]+"," ",original).replace("-\n","") if normalize else None
            meta=ProcessingMetadata(backend=profile.backend,model_profile=profile.name,model_name=profile.model,retries=retries,durations_ms={"total":(time.monotonic()-started)*1000},preprocessing={"pages":prep},tiles=tiles_meta)
            document=DocumentRecognition(document_id=str(uuid.uuid4()),pages=pages,original_text=original,normalized_text=normalized,metadata=meta,partial=len(pages)!=len(rendered))
            return RecognitionResult(document,images,rendered)
