from dataclasses import dataclass
from typing import Protocol
from app.services.recognition.pipeline import RecognitionResult
@dataclass(frozen=True)
class ExportOptions:
    preserve_layout:bool=True
    include_bounding_boxes:bool=True
    include_processing_metadata:bool=True
class Exporter(Protocol):
    format:str;mime_type:str;extension:str
    def export(self,result:RecognitionResult,options:ExportOptions)->bytes:...
