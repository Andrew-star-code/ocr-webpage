import html
from app.schemas.recognition import HeadingBlock,ListBlock,TableBlock
class HtmlExporter:
 format="html";mime_type="text/html; charset=utf-8";extension="html"
 def export_table_fragment(self,table):
  out=["<table>"];header=min(table.header_rows,len(table.rows))
  if header:
   out.append("<thead>")
   for row in table.rows[:header]:out.append(self._row(row))
   out.append("</thead>")
  out.append("<tbody>")
  for row in table.rows[header:]:out.append(self._row(row))
  out.append("</tbody></table>");return "".join(out)
 def _row(self,row):
  cells=[]
  for cell in row.cells:
   tag="th" if cell.is_header else "td";cells.append(f'<{tag} rowspan="{cell.row_span}" colspan="{cell.column_span}">{html.escape(cell.text)}</{tag}>')
  return "<tr>"+"".join(cells)+"</tr>"
 def export(self,result,options):
  out=['<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>OCR document</title></head><body>']
  for page in result.document.pages:
   out.append(f'<section data-page="{page.page_number}">')
   for block in sorted(page.blocks,key=lambda x:x.reading_order):
    value=html.escape(block.normalized_text or block.original_text)
    if isinstance(block,HeadingBlock) and value:out.append(f"<h{block.heading_level}>{value}</h{block.heading_level}>")
    elif isinstance(block,ListBlock):
     tag="ol" if block.ordered else "ul";out.append(f"<{tag}>"+"".join(f'<li data-level="{item.level}">{html.escape(item.text)}</li>' for item in block.items)+f"</{tag}>")
    elif isinstance(block,TableBlock):out.append(self.export_table_fragment(block))
    elif value:out.append(f"<p>{value}</p>")
   out.append("</section>")
  return "".join(out+["</body></html>"]).encode()
