from app.services.exporters.docx_exporter import DocxExporter
from app.services.exporters.html_exporter import HtmlExporter
from app.services.exporters.json_exporter import JsonExporter
from app.services.exporters.markdown_exporter import MarkdownExporter
from app.services.exporters.searchable_pdf_exporter import SearchablePdfExporter
from app.services.exporters.txt_exporter import TxtExporter


class ExporterRegistry:
    def __init__(self):
        self._items = {
            e.format: e
            for e in (
                JsonExporter(),
                DocxExporter(),
                TxtExporter(),
                MarkdownExporter(),
                HtmlExporter(),
                SearchablePdfExporter(),
            )
        }

    def get(self, name):
        return self._items.get(name)

    def formats(self):
        return [
            {"format": e.format, "mime_type": e.mime_type, "extension": e.extension}
            for e in self._items.values()
        ]
