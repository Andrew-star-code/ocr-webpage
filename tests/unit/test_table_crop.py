import io
import json

import pytest
from PIL import Image

from app.core.config import Settings
from app.schemas.recognition import (
    BoundingBox,
    PageRecognition,
    RecognitionWarning,
    TableBlock,
    TableCell,
    TableRow,
)
from app.services.recognition.pipeline import RecognitionPipeline
from app.services.vision.base import VisionResponse
from app.services.vision.profiles import ProfileRegistry


class Backend:
    name = "ollama"

    async def recognize_page(self, image, prompt, schema, options):
        page = {
            "page_number": 1,
            "width": 100,
            "height": 100,
            "blocks": [
                {
                    "id": "new",
                    "type": "table",
                    "reading_order": 1,
                    "bbox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1},
                    "row_count": 1,
                    "column_count": 1,
                    "rows": [{"cells": [{"row_index": 0, "column_index": 0, "text": "A"}]}],
                }
            ],
        }
        return VisionResponse(json.dumps(page))


class Backends:
    def __init__(self):
        self.backends = {"ollama": Backend()}

    def get(self, name):
        return self.backends[name]


@pytest.mark.asyncio
async def test_warning_table_is_recognized_from_crop():
    image = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(image, "PNG")
    table = TableBlock(
        id="old",
        reading_order=1,
        bbox=BoundingBox(x1=0.2, y1=0.2, x2=0.8, y2=0.8),
        row_count=1,
        column_count=1,
        rows=[TableRow(cells=[TableCell(row_index=0, column_index=0, text="?")])],
        warnings=[RecognitionWarning(code="unclear", message="unclear")],
    )
    page = PageRecognition(page_number=1, width=200, height=200, blocks=[table])
    pipeline = RecognitionPipeline(
        Settings(),
        Backends(),
        ProfileRegistry.load(__import__("pathlib").Path("config/model_profiles")),
    )
    refined = await pipeline._table_crops(
        page, image.getvalue(), pipeline.profiles.get("default"), "rus", None
    )
    assert refined.blocks[0].id == "old" and refined.blocks[0].rows[0].cells[0].text == "A"
