import io
from dataclasses import dataclass
from difflib import SequenceMatcher

from PIL import Image

from app.schemas.recognition import BoundingBox


@dataclass(slots=True)
class Tile:
    id: str
    image: bytes
    x: int
    y: int
    width: int
    height: int
    page_width: int
    page_height: int


def make_tiles(data, size=1600, overlap=160):
    image = Image.open(io.BytesIO(data))
    result = []
    step = max(1, size - overlap)
    for y in range(0, image.height, step):
        for x in range(0, image.width, step):
            x2 = min(x + size, image.width)
            y2 = min(y + size, image.height)
            out = io.BytesIO()
            image.crop((x, y, x2, y2)).save(out, "PNG")
            result.append(
                Tile(
                    f"tile-{len(result) + 1}",
                    out.getvalue(),
                    x,
                    y,
                    x2 - x,
                    y2 - y,
                    image.width,
                    image.height,
                )
            )
            if x2 == image.width:
                break
        if y2 == image.height:
            break
    return result


def transform_bbox(box, tile):
    if box is None:
        return None
    return BoundingBox(
        x1=(tile.x + box.x1 * tile.width) / tile.page_width,
        y1=(tile.y + box.y1 * tile.height) / tile.page_height,
        x2=(tile.x + box.x2 * tile.width) / tile.page_width,
        y2=(tile.y + box.y2 * tile.height) / tile.page_height,
    )


def transform_page(page, tile):
    blocks = [
        block.model_copy(update={"bbox": transform_bbox(block.bbox, tile), "tile_id": tile.id})
        for block in page.blocks
    ]
    return page.model_copy(
        update={"width": tile.page_width, "height": tile.page_height, "blocks": blocks}
    )


def _iou(a, b):
    if not a or not b:
        return 0
    area = max(0, min(a.x2, b.x2) - max(a.x1, b.x1)) * max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - area
    return area / union if union else 0


def _duplicate(a, b):
    if a.type != b.type or not a.bbox or not b.bbox:
        return False
    if a.type == "table":
        return _iou(a.bbox, b.bbox) > 0.5
    ta = a.original_text.strip()
    tb = b.original_text.strip()
    if len(ta) < 8 or len(tb) < 8:
        return ta == tb and _iou(a.bbox, b.bbox) > 0.65
    similarity = SequenceMatcher(None, ta, tb).ratio()
    text_refinement = ta in tb or tb in ta
    return (similarity > 0.92 or text_refinement) and _iou(a.bbox, b.bbox) > 0.35


def _refine(overview, detail):
    """Apply tile detail without discarding the overview's global-order identity."""
    identity = {"id", "source_id", "reading_order", "original_text", "warnings"}
    update = {
        field: getattr(detail, field)
        for field in type(detail).model_fields
        if field not in identity
    }
    update["bbox"] = detail.bbox or overview.bbox
    update["warnings"] = [*overview.warnings, *detail.warnings]
    if len(detail.original_text.strip()) >= len(overview.original_text.strip()):
        update["original_text"] = detail.original_text
    return overview.model_copy(update=update)


def merge_pages(base, partials):
    details = list(base.blocks)
    for page in partials:
        for candidate in page.blocks:
            matches = [block for block in details if _duplicate(candidate, block)]
            if not matches:
                details.append(candidate)
            else:
                match = matches[0]
                details[details.index(match)] = _refine(match, candidate)
    return base.model_copy(update={"blocks": details})
