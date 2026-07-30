from dataclasses import dataclass
from difflib import SequenceMatcher
from app.schemas.recognition import PageRecognition
@dataclass
class Column:
 left:float;right:float;blocks:list

def _iou(a,b):
 if not a or not b:return 0.0
 area=max(0,min(a.x2,b.x2)-max(a.x1,b.x1))*max(0,min(a.y2,b.y2)-max(a.y1,b.y1));union=(a.x2-a.x1)*(a.y2-a.y1)+(b.x2-b.x1)*(b.y2-b.y1)-area
 return area/union if union else 0.0
def _match(a,b):
 if a.type!=b.type or not a.bbox or not b.bbox:return 0.0
 text=SequenceMatcher(None,a.original_text.strip(),b.original_text.strip()).ratio() if a.original_text and b.original_text else 0
 ac=(a.bbox.x1+a.bbox.x2)/2,(a.bbox.y1+a.bbox.y2)/2;bc=(b.bbox.x1+b.bbox.x2)/2,(b.bbox.y1+b.bbox.y2)/2
 proximity=max(0,1-((ac[0]-bc[0])**2+(ac[1]-bc[1])**2)**.5*3)
 return .5*_iou(a.bbox,b.bbox)+.35*text+.15*proximity
def _columns(blocks):
 narrow=[b for b in blocks if b.bbox and b.type not in {"footer","page_number"} and b.bbox.x2-b.bbox.x1<.72]
 columns=[]
 for block in sorted(narrow,key=lambda b:(b.bbox.x1,b.bbox.x2)):
  best=None
  for col in columns:
   overlap=max(0,min(col.right,block.bbox.x2)-max(col.left,block.bbox.x1));den=min(col.right-col.left,block.bbox.x2-block.bbox.x1)
   if den and overlap/den>.35:best=col;break
  if best:best.left=min(best.left,block.bbox.x1);best.right=max(best.right,block.bbox.x2);best.blocks.append(block)
  else:columns.append(Column(block.bbox.x1,block.bbox.x2,[block]))
 return sorted(columns,key=lambda c:c.left)
def order_without_overview(blocks):
 boxes=[b for b in blocks if b.bbox];unboxed=[b for b in blocks if not b.bbox]
 footers=[b for b in boxes if b.type in {"footer","page_number"}];body=[b for b in boxes if b not in footers]
 spanning=[b for b in body if b.bbox.x2-b.bbox.x1>=.72];columns=_columns(body)
 ordered=[];boundaries=sorted({0.0,1.0}|{b.bbox.y1 for b in spanning}|{b.bbox.y2 for b in spanning})
 # Wide headings/tables partition the page; each vertical band is read by columns left-to-right.
 for start,end in zip(boundaries,boundaries[1:]):
  ordered.extend(sorted([b for b in spanning if start<=b.bbox.y1<end],key=lambda b:(b.bbox.y1,b.bbox.x1)))
  for col in columns:ordered.extend(sorted([b for b in col.blocks if start<=b.bbox.y1<end],key=lambda b:(b.bbox.y1,b.bbox.x1,b.bbox.y2)))
 seen=set();ordered=[b for b in ordered if not (id(b) in seen or seen.add(id(b)))]
 ordered.extend(sorted([b for b in body if b not in ordered],key=lambda b:(b.bbox.y1,b.bbox.x1)))
 ordered.extend(sorted(footers,key=lambda b:(b.type=="page_number",b.bbox.y1,b.bbox.x1)));ordered.extend(unboxed)
 return ordered
def merge_with_overview(overview,details):
 result=list(sorted(overview,key=lambda b:b.reading_order));new=[]
 for candidate in details:
  scored=[(_match(base,candidate),i,base) for i,base in enumerate(result)];score,index,base=max(scored,default=(0,-1,None))
  if score>=.42:
   # Preserve global ID/order and model provenance while accepting more complete detail.
   if len(candidate.original_text)>=len(base.original_text):result[index]=candidate.model_copy(update={"id":base.id,"source_id":candidate.source_id or candidate.id,"reading_order":base.reading_order})
  else:new.append(candidate)
 combined=result+new
 if new:combined=order_without_overview(combined)
 return combined
def finalize_page(page,overview_blocks=None):
 blocks=merge_with_overview(overview_blocks,page.blocks) if overview_blocks is not None else order_without_overview(page.blocks)
 stable=[b.model_copy(update={"source_id":b.source_id or b.id,"id":f"page-{page.page_number}-block-{i}","reading_order":i}) for i,b in enumerate(blocks,1)]
 payload=page.model_dump();payload["blocks"]=[b.model_dump() for b in stable]
 return PageRecognition.model_validate(payload)
