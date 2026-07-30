import html
from app.schemas.recognition import HeadingBlock,ListBlock,TableBlock
class HtmlExporter:
 format="html";mime_type="text/html; charset=utf-8";extension="html"
 def export(self,result,options):
  out=['<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>OCR document</title></head><body>']
  for page in result.document.pages:
   out.append(f'<section data-page="{page.page_number}">')
   for b in sorted(page.blocks,key=lambda x:x.reading_order):
    value=html.escape(b.normalized_text or b.original_text)
    if isinstance(b,HeadingBlock) and value:out.append(f"<h{b.heading_level}>{value}</h{b.heading_level}>")
    elif isinstance(b,ListBlock):
     tag="ol" if b.ordered else "ul";out.append(f"<{tag}>"+"".join(f'<li data-level="{i.level}">{html.escape(i.text)}</li>' for i in b.items)+f"</{tag}>")
    elif isinstance(b,TableBlock):
     header=min(b.header_rows,len(b.rows));out.append("<table>")
     if header:
      out.append("<thead>")
      for row in b.rows[:header]:out.append("<tr>"+"".join(f'<{"th" if c.is_header else "td"} rowspan="{c.row_span}" colspan="{c.column_span}">{html.escape(c.text)}</{"th" if c.is_header else "td"}>' for c in row.cells)+"</tr>")
      out.append("</thead>")
     out.append("<tbody>")
     for row in b.rows[header:]:out.append("<tr>"+"".join(f'<{"th" if c.is_header else "td"} rowspan="{c.row_span}" colspan="{c.column_span}">{html.escape(c.text)}</{"th" if c.is_header else "td"}>' for c in row.cells)+"</tr>")
     out.append("</tbody></table>")
    elif value:out.append(f"<p>{value}</p>")
   out.append("</section>")
  return "".join(out+["</body></html>"]).encode()
