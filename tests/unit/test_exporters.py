from app.schemas.recognition import *
from app.services.exporters.all import EXPORTERS
def document():
 p=PageRecognition(page_number=1,width=100,height=100,blocks=[HeadingBlock(id="h",reading_order=1,original_text="Заголовок"),ParagraphBlock(id="p",reading_order=2,original_text="Текст")])
 return DocumentRecognition(document_id="d",pages=[p],original_text="Заголовок\nТекст",metadata=ProcessingMetadata(backend="ollama",model_profile="default",model_name="m"))
def test_all_exports():
 d=document()
 for name,exporter in EXPORTERS.items(): assert len(exporter(d))>20,name
