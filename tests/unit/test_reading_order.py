from app.schemas.recognition import (
    BoundingBox,
    GenericBlock,
    HeadingBlock,
    PageRecognition,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
)
from app.services.layout.reading_order import finalize_page, resolve_reading_order


def p(id, x1, y1, x2, y2, text=None):
    return ParagraphBlock(
        id=id,
        reading_order=1,
        original_text=text or id,
        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
    )


def texts(page):
    return [b.original_text for b in page.blocks]


def page(blocks):
    return PageRecognition(
        page_number=1,
        width=1000,
        height=1000,
        blocks=[
            block.model_copy(
                update={"source_id": block.id, "id": f"input-{index}", "reading_order": index}
            )
            for index, block in enumerate(blocks, 1)
        ],
    )


def test_two_columns_are_not_interleaved_and_ids_are_stable():
    result = finalize_page(
        page(
            [
                p("block-1", 0.55, 0.1, 0.9, 0.2, "R1"),
                p("block-1", 0.1, 0.1, 0.45, 0.2, "L1"),
                p("block-1", 0.55, 0.3, 0.9, 0.4, "R2"),
                p("block-1", 0.1, 0.3, 0.45, 0.4, "L2"),
            ]
        )
    )
    assert texts(result) == ["L1", "L2", "R1", "R2"]
    assert [b.id for b in result.blocks] == [f"page-1-block-{i}" for i in range(1, 5)]


def test_spanning_heading_footer_and_equal_y():
    heading = HeadingBlock(
        id="h",
        reading_order=1,
        original_text="H",
        bbox=BoundingBox(x1=0.05, y1=0.02, x2=0.95, y2=0.08),
    )
    footer = GenericBlock(
        id="f",
        type="footer",
        reading_order=4,
        original_text="F",
        bbox=BoundingBox(x1=0.1, y1=0.9, x2=0.9, y2=0.95),
    )
    result = finalize_page(
        page([p("r", 0.55, 0.1, 0.9, 0.2), heading, p("l", 0.1, 0.1, 0.45, 0.2), footer])
    )
    assert texts(result) == ["H", "l", "r", "F"]


def test_spanning_table_partitions_columns():
    table = TableBlock(
        id="t",
        reading_order=3,
        row_count=1,
        column_count=1,
        rows=[TableRow(cells=[TableCell(row_index=0, column_index=0, text="T")])],
        original_text="T",
        bbox=BoundingBox(x1=0.05, y1=0.45, x2=0.95, y2=0.6),
    )
    result = finalize_page(
        page(
            [
                p("r2", 0.55, 0.7, 0.9, 0.8),
                p("l1", 0.1, 0.1, 0.45, 0.2),
                table,
                p("r1", 0.55, 0.1, 0.9, 0.2),
                p("l2", 0.1, 0.7, 0.45, 0.8),
            ]
        )
    )
    assert texts(result) == ["l1", "r1", "T", "l2", "r2"]


def test_overview_order_survives_tile_refinement():
    overview = [p("a", 0.1, 0.1, 0.4, 0.2, "first"), p("b", 0.1, 0.3, 0.4, 0.4, "second")]
    overview = [b.model_copy(update={"reading_order": i}) for i, b in enumerate(overview, 1)]
    detail = [p("block-1", 0.1, 0.3, 0.4, 0.4, "second refined")]
    merged = resolve_reading_order(detail, overview)
    assert merged[1].original_text == "second refined" and merged[1].reading_order == 2


def test_two_tiles_with_same_model_id_receive_unique_final_ids():
    from app.services.tiling.tiles import merge_pages

    left = page([p("block-1", 0.05, 0.1, 0.4, 0.2, "same")])
    right = page([p("block-1", 0.6, 0.1, 0.95, 0.2, "same")])
    empty = PageRecognition(page_number=1, width=1000, height=1000, blocks=[])
    merged = finalize_page(merge_pages(empty, [left, right]))
    assert len(merged.blocks) == 2
    assert len({block.id for block in merged.blocks}) == 2
    assert len({block.reading_order for block in merged.blocks}) == 2
    PageRecognition.model_validate(merged.model_dump())


def test_tile_refinement_keeps_overview_identity_and_far_block():
    from app.services.tiling.tiles import merge_pages

    overview = page([p("overview", 0.05, 0.1, 0.4, 0.2, "short text")])
    overview_block = overview.blocks[0]
    close_detail = page([p("tile", 0.05, 0.1, 0.4, 0.2, "short text refined")])
    far_detail = page([p("tile", 0.6, 0.1, 0.95, 0.2, "short text")])
    merged = merge_pages(overview, [close_detail, far_detail])

    assert len(merged.blocks) == 2
    assert merged.blocks[0].id == overview_block.id
    assert merged.blocks[0].source_id == overview_block.source_id
    assert merged.blocks[0].reading_order == overview_block.reading_order
    assert merged.blocks[0].original_text == "short text refined"


def test_tile_table_refinement_copies_validated_structure():
    from app.services.tiling.tiles import merge_pages

    overview_table = TableBlock(
        id="overview-table",
        source_id="model-table",
        reading_order=1,
        original_text="A",
        bbox=BoundingBox(x1=0.1, y1=0.1, x2=0.9, y2=0.4),
        row_count=1,
        column_count=1,
        rows=[TableRow(cells=[TableCell(row_index=0, column_index=0, text="A")])],
    )
    detail_table = overview_table.model_copy(
        update={
            "id": "tile-table",
            "source_id": "tile-model-table",
            "original_text": "A refined",
            "row_count": 2,
            "rows": [
                TableRow(cells=[TableCell(row_index=0, column_index=0, text="A")]),
                TableRow(cells=[TableCell(row_index=1, column_index=0, text="B")]),
            ],
        }
    )
    base = PageRecognition(page_number=1, width=1000, height=1000, blocks=[overview_table])
    partial = PageRecognition(page_number=1, width=1000, height=1000, blocks=[detail_table])
    merged = merge_pages(base, [partial])

    assert merged.blocks[0].id == "overview-table"
    assert merged.blocks[0].source_id == "model-table"
    assert merged.blocks[0].row_count == 2
    assert merged.blocks[0].rows[1].cells[0].text == "B"


def test_unmatched_detail_is_inserted_without_reordering_overview():
    overview = [
        p("a", 0.1, 0.1, 0.4, 0.2, "first"),
        p("b", 0.1, 0.5, 0.4, 0.6, "third"),
        p("c", 0.6, 0.1, 0.9, 0.2, "right"),
    ]
    overview = [
        block.model_copy(update={"reading_order": index}) for index, block in enumerate(overview, 1)
    ]
    new = p("tile-new", 0.1, 0.3, 0.4, 0.4, "second")
    ordered = resolve_reading_order([new], overview)
    assert [block.original_text for block in ordered] == ["first", "second", "third", "right"]


def test_unmatched_footer_does_not_reorder_overview_body():
    overview = [p("a", 0.1, 0.1, 0.4, 0.2), p("b", 0.6, 0.1, 0.9, 0.2)]
    overview = [
        block.model_copy(update={"reading_order": index}) for index, block in enumerate(overview, 1)
    ]
    footer = GenericBlock(
        id="footer",
        type="footer",
        reading_order=1,
        original_text="footer",
        bbox=BoundingBox(x1=0.1, y1=0.9, x2=0.9, y2=0.95),
    )
    ordered = resolve_reading_order([footer], overview)
    assert [block.original_text for block in ordered] == ["a", "b", "footer"]
