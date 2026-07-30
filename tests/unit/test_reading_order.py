from app.schemas.recognition import BoundingBox,GenericBlock,HeadingBlock,PageRecognition,ParagraphBlock,TableBlock,TableRow,TableCell
from app.services.layout.reading_order import finalize_page,merge_with_overview
def p(id,x1,y1,x2,y2,text=None):return ParagraphBlock(id=id,reading_order=1,original_text=text or id,bbox=BoundingBox(x1=x1,y1=y1,x2=x2,y2=y2))
def texts(page):return [b.original_text for b in page.blocks]
def page(blocks):return PageRecognition(page_number=1,width=1000,height=1000,blocks=[b.model_copy(update={"reading_order":i}) for i,b in enumerate(blocks,1)])
def test_two_columns_are_not_interleaved_and_ids_are_stable():
 result=finalize_page(page([p("block-1",.55,.1,.9,.2,"R1"),p("block-1",.1,.1,.45,.2,"L1"),p("block-1",.55,.3,.9,.4,"R2"),p("block-1",.1,.3,.45,.4,"L2")]))
 assert texts(result)==["L1","L2","R1","R2"];assert [b.id for b in result.blocks]==[f"page-1-block-{i}" for i in range(1,5)]
def test_spanning_heading_footer_and_equal_y():
 heading=HeadingBlock(id="h",reading_order=1,original_text="H",bbox=BoundingBox(x1=.05,y1=.02,x2=.95,y2=.08));footer=GenericBlock(id="f",type="footer",reading_order=4,original_text="F",bbox=BoundingBox(x1=.1,y1=.9,x2=.9,y2=.95));result=finalize_page(page([p("r",.55,.1,.9,.2),heading,p("l",.1,.1,.45,.2),footer]));assert texts(result)==["H","l","r","F"]
def test_spanning_table_partitions_columns():
 table=TableBlock(id="t",reading_order=3,row_count=1,column_count=1,rows=[TableRow(cells=[TableCell(row_index=0,column_index=0,text="T")])],original_text="T",bbox=BoundingBox(x1=.05,y1=.45,x2=.95,y2=.6));result=finalize_page(page([p("r2",.55,.7,.9,.8),p("l1",.1,.1,.45,.2),table,p("r1",.55,.1,.9,.2),p("l2",.1,.7,.45,.8)]));assert texts(result)==["l1","r1","T","l2","r2"]
def test_overview_order_survives_tile_refinement():
 overview=[p("a",.1,.1,.4,.2,"first"),p("b",.1,.3,.4,.4,"second")];overview=[b.model_copy(update={"reading_order":i}) for i,b in enumerate(overview,1)];detail=[p("block-1",.1,.3,.4,.4,"second refined")];merged=merge_with_overview(overview,detail);assert merged[1].original_text=="second refined" and merged[1].reading_order==2
def test_two_tiles_with_same_model_id_receive_unique_final_ids():
 from app.services.tiling.tiles import merge_pages
 left=page([p("block-1",.05,.1,.4,.2,"same")]);right=page([p("block-1",.6,.1,.95,.2,"same")]);empty=PageRecognition(page_number=1,width=1000,height=1000,blocks=[]);merged=merge_pages(empty,[left,right]);assert len(merged.blocks)==2 and len({b.id for b in merged.blocks})==2 and len({b.reading_order for b in merged.blocks})==2;PageRecognition.model_validate(merged.model_dump())
