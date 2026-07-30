from app.schemas.recognition import ListBlock,TableBlock
class TxtExporter:
 format="txt";mime_type="text/plain; charset=utf-8";extension="txt"
 def export(self,result,options):
  chunks=[]
  for page in result.document.pages:
   chunks.append(f"--- Страница {page.page_number} ---")
   for block in sorted(page.blocks,key=lambda x:x.reading_order):
    if isinstance(block,ListBlock):chunks.extend((f"{i+1}. " if block.ordered else "• ")+item.text for i,item in enumerate(block.items))
    elif isinstance(block,TableBlock):chunks.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
    elif block.original_text:chunks.append(block.normalized_text or block.original_text)
  return "\n\n".join(chunks).encode()
