from typing import Annotated, Literal
from pydantic import BaseModel, Field, model_validator

class BoundingBox(BaseModel):
    x1: float = Field(ge=0, le=1); y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1); y2: float = Field(ge=0, le=1)
    @model_validator(mode="after")
    def ordered(self):
        if self.x1 >= self.x2 or self.y1 >= self.y2: raise ValueError("invalid bounding box")
        return self
class TextStyle(BaseModel):
    bold: bool = False; italic: bool = False; underline: bool = False
    alignment: Literal["left","center","right","justify"] = "left"
class RecognitionWarning(BaseModel):
    code: str; message: str
class BlockBase(BaseModel):
    id: str; source_id: str | None = None; reading_order: int = Field(ge=0); bbox: BoundingBox | None = None
    original_text: str = ""; normalized_text: str | None = None; language: str | None = None
    style: TextStyle = Field(default_factory=TextStyle); warnings: list[RecognitionWarning] = Field(default_factory=list)
    source: str = "vision"; tile_id: str | None = None; model_reported_confidence: float | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
class ParagraphBlock(BlockBase): type: Literal["paragraph"] = "paragraph"
class HeadingBlock(BlockBase): type: Literal["heading"] = "heading"; heading_level: int = Field(default=1, ge=1, le=6)
class ListItem(BaseModel): text: str; level: int = Field(default=0, ge=0)
class ListBlock(BlockBase): type: Literal["list"] = "list"; ordered: bool = False; items: list[ListItem]
class TableCell(BaseModel):
    row_index: int = Field(ge=0); column_index: int = Field(ge=0); row_span: int = Field(default=1, ge=1); column_span: int = Field(default=1, ge=1); is_header: bool = False; text: str = ""
class TableRow(BaseModel): cells: list[TableCell]
class TableBlock(BlockBase):
    type: Literal["table"] = "table"; caption: str | None = None; row_count: int = Field(ge=1); column_count: int = Field(ge=1); header_rows: int = Field(default=0, ge=0); rows: list[TableRow]; continues_on_next_page: bool = False
    @model_validator(mode="after")
    def dimensions(self):
        positions=set()
        for row in self.rows:
            for c in row.cells:
                if c.row_index + c.row_span > self.row_count or c.column_index + c.column_span > self.column_count: raise ValueError("table cell outside dimensions")
                for position in ((r,col) for r in range(c.row_index,c.row_index+c.row_span) for col in range(c.column_index,c.column_index+c.column_span)):
                    if position in positions: raise ValueError("overlapping table cells")
                    positions.add(position)
        return self
class GenericBlock(BlockBase): type: Literal["image","caption","footnote","header","footer","page_number","signature","stamp","form_field","checkbox","unknown"]
DocumentBlock = Annotated[ParagraphBlock | HeadingBlock | ListBlock | TableBlock | GenericBlock, Field(discriminator="type")]
class PageRecognition(BaseModel):
    page_number: int = Field(ge=1); width: int = Field(gt=0); height: int = Field(gt=0); rotation: int = 0
    detected_languages: list[str] = Field(default_factory=list); blocks: list[DocumentBlock]; warnings: list[RecognitionWarning] = Field(default_factory=list)
    validation_score: float = 1; consistency_score: float = 1; quality_score: float = 1
    @model_validator(mode="after")
    def unique_order(self):
        ids=[b.id for b in self.blocks]; orders=[b.reading_order for b in self.blocks]
        if len(ids)!=len(set(ids)): raise ValueError("duplicate block id")
        if len(orders)!=len(set(orders)): raise ValueError("duplicate reading_order")
        return self
class ProcessingMetadata(BaseModel):
    backend: str; model_profile: str; model_name: str; retries: int = 0; durations_ms: dict[str,float] = Field(default_factory=dict); preprocessing: dict = Field(default_factory=dict); tiles: list[dict] = Field(default_factory=list); quality_score_is_heuristic: bool = True
class DocumentRecognition(BaseModel):
    document_id: str; pages: list[PageRecognition]; original_text: str; normalized_text: str | None = None; metadata: ProcessingMetadata; warnings: list[RecognitionWarning] = Field(default_factory=list); partial: bool = False
