from app.schemas.recognition import HeadingBlock,ListBlock,TableBlock
from app.services.exporters.html_exporter import HtmlExporter
def esc(value):return value.replace("\\","\\\\").replace("|","\\|").replace("\n","<br>")
class MarkdownExporter:
 format="md";mime_type="text/markdown; charset=utf-8";extension="md"
 def export(self,result,options):
  out=[]
  for page in result.document.pages:
   out.append(f"<!-- page {page.page_number} -->\n\n---")
   for b in sorted(page.blocks,key=lambda x:x.reading_order):
    value=b.normalized_text or b.original_text
    if isinstance(b,HeadingBlock) and value:out.append("#"*b.heading_level+" "+value)
    elif isinstance(b,ListBlock):out.extend("  "*item.level+(f"{i+1}. " if b.ordered else "- ")+item.text for i,item in enumerate(b.items))
    elif isinstance(b,TableBlock):
     merged=any(c.row_span>1 or c.column_span>1 for row in b.rows for c in row.cells)
     if merged:out.append(HtmlExporter().export_table_fragment(b))
     else:
      width=max((len(r.cells) for r in b.rows),default=0);rows=[[esc(c.text) for c in r.cells]+[""]*(width-len(r.cells)) for r in b.rows]
      if rows and width:out.extend(["| "+" | ".join(rows[0])+" |","| "+" | ".join("---" for _ in range(width))+" |"]+["| "+" | ".join(r)+" |" for r in rows[1:]])
    elif value:out.append(value)
  return "\n\n".join(out).encode()
