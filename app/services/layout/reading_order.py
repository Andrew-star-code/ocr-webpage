from dataclasses import dataclass
from difflib import SequenceMatcher

from app.schemas.recognition import PageRecognition


@dataclass
class Column:
    left: float
    right: float
    blocks: list


def _iou(a, b):
    if not a or not b:
        return 0.0
    intersection = max(0, min(a.x2, b.x2) - max(a.x1, b.x1)) * max(
        0, min(a.y2, b.y2) - max(a.y1, b.y1)
    )
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - intersection
    return intersection / union if union else 0.0


def _match(a, b):
    if a.type != b.type or not a.bbox or not b.bbox:
        return 0.0
    text = (
        SequenceMatcher(None, a.original_text.strip(), b.original_text.strip()).ratio()
        if a.original_text and b.original_text
        else 0
    )
    a_center = ((a.bbox.x1 + a.bbox.x2) / 2, (a.bbox.y1 + a.bbox.y2) / 2)
    b_center = ((b.bbox.x1 + b.bbox.x2) / 2, (b.bbox.y1 + b.bbox.y2) / 2)
    distance = ((a_center[0] - b_center[0]) ** 2 + (a_center[1] - b_center[1]) ** 2) ** 0.5
    proximity = max(0, 1 - distance * 3)
    return 0.5 * _iou(a.bbox, b.bbox) + 0.35 * text + 0.15 * proximity


def _columns(blocks):
    narrow = [
        block
        for block in blocks
        if block.bbox
        and block.type not in {"footer", "page_number"}
        and block.bbox.x2 - block.bbox.x1 < 0.72
    ]
    columns = []
    for block in sorted(narrow, key=lambda item: (item.bbox.x1, item.bbox.x2, item.id)):
        selected = None
        for column in columns:
            overlap = max(0, min(column.right, block.bbox.x2) - max(column.left, block.bbox.x1))
            denominator = min(column.right - column.left, block.bbox.x2 - block.bbox.x1)
            if denominator and overlap / denominator > 0.35:
                selected = column
                break
        if selected:
            selected.left = min(selected.left, block.bbox.x1)
            selected.right = max(selected.right, block.bbox.x2)
            selected.blocks.append(block)
        else:
            columns.append(Column(block.bbox.x1, block.bbox.x2, [block]))
    return sorted(columns, key=lambda item: item.left)


def order_without_overview(blocks):
    boxes = [block for block in blocks if block.bbox]
    unboxed = [block for block in blocks if not block.bbox]
    footers = [block for block in boxes if block.type in {"footer", "page_number"}]
    body = [block for block in boxes if block not in footers]
    spanning = [block for block in body if block.bbox.x2 - block.bbox.x1 >= 0.72]
    columns = _columns(body)
    ordered = []
    boundaries = sorted(
        {0.0, 1.0} | {block.bbox.y1 for block in spanning} | {block.bbox.y2 for block in spanning}
    )
    for start, end in zip(boundaries, boundaries[1:]):
        ordered.extend(
            sorted(
                [block for block in spanning if start <= block.bbox.y1 < end],
                key=lambda item: (item.bbox.y1, item.bbox.x1, item.id),
            )
        )
        for column in columns:
            ordered.extend(
                sorted(
                    [block for block in column.blocks if start <= block.bbox.y1 < end],
                    key=lambda item: (item.bbox.y1, item.bbox.x1, item.bbox.y2, item.id),
                )
            )
    seen = set()
    ordered = [block for block in ordered if not (id(block) in seen or seen.add(id(block)))]
    ordered.extend(block for block in body if block not in ordered)
    ordered.extend(
        sorted(
            footers,
            key=lambda item: (item.type == "page_number", item.bbox.y1, item.bbox.x1, item.id),
        )
    )
    ordered.extend(unboxed)
    return ordered


def _insert_unmatched(ordered, candidate):
    if candidate.type in {"footer", "page_number"} or not candidate.bbox:
        ordered.append(candidate)
        return
    candidates = [
        (index, block)
        for index, block in enumerate(ordered)
        if block.bbox and block.type not in {"footer", "page_number"}
    ]
    if not candidates:
        ordered.insert(0, candidate)
        return
    same_column = [
        pair
        for pair in candidates
        if max(0, min(pair[1].bbox.x2, candidate.bbox.x2) - max(pair[1].bbox.x1, candidate.bbox.x1))
        > 0
    ]
    pool = same_column or candidates
    index, neighbor = min(
        pool,
        key=lambda pair: (
            abs(
                (pair[1].bbox.y1 + pair[1].bbox.y2) / 2
                - (candidate.bbox.y1 + candidate.bbox.y2) / 2
            ),
            pair[0],
        ),
    )
    insert_at = index if candidate.bbox.y1 < neighbor.bbox.y1 else index + 1
    ordered.insert(insert_at, candidate)


def resolve_reading_order(blocks, overview_blocks=None):
    if overview_blocks is None:
        return order_without_overview(blocks)
    ordered = list(sorted(overview_blocks, key=lambda block: block.reading_order))
    unmatched = []
    for candidate in blocks:
        scores = [(_match(base, candidate), index, base) for index, base in enumerate(ordered)]
        score, index, base = max(scores, default=(0, -1, None))
        if score >= 0.42:
            if len(candidate.original_text) >= len(base.original_text):
                ordered[index] = candidate.model_copy(
                    update={
                        "id": base.id,
                        "source_id": candidate.source_id or candidate.id,
                        "reading_order": base.reading_order,
                    }
                )
        else:
            unmatched.append(candidate)
    for candidate in sorted(
        unmatched,
        key=lambda block: (
            block.type in {"footer", "page_number"},
            block.bbox.y1 if block.bbox else 2,
            block.bbox.x1 if block.bbox else 2,
            block.id,
        ),
    ):
        _insert_unmatched(ordered, candidate)
    return ordered


def finalize_page(page, overview_blocks=None):
    blocks = resolve_reading_order(page.blocks, overview_blocks)
    stable = [
        block.model_copy(
            update={
                "source_id": block.source_id or block.id,
                "id": f"page-{page.page_number}-block-{index}",
                "reading_order": index,
            }
        )
        for index, block in enumerate(blocks, 1)
    ]
    payload = page.model_dump()
    payload["blocks"] = [block.model_dump() for block in stable]
    return PageRecognition.model_validate(payload)
