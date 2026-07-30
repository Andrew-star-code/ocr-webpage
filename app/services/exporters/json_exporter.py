import json
class JsonExporter:
 format="json";mime_type="application/json";extension="json"
 def export(self,result,options):
  data=result.document.model_dump(mode="json")
  if not options.include_bounding_boxes:
   for page in data["pages"]:
    for block in page["blocks"]:block.pop("bbox",None)
  if not options.include_processing_metadata:data.pop("metadata",None)
  return json.dumps(data,ensure_ascii=False,indent=2).encode()
