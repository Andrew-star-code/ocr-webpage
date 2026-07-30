from pathlib import Path

import fitz


class SearchablePdfExporter:
    format = "searchable_pdf"
    mime_type = "application/pdf"
    extension = "pdf"

    def _font(self):
        for name in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ):
            if Path(name).is_file():
                return name
        raise RuntimeError("DejaVu Sans is required for Cyrillic searchable PDF")

    def export(self, result, options):
        output = fitz.open()
        fontfile = self._font()
        for recognized, rendered, image in zip(
            result.document.pages, result.rendered_pages, result.page_images, strict=True
        ):
            width = rendered.pdf_width or rendered.width
            height = rendered.pdf_height or rendered.height
            page = output.new_page(width=width, height=height)
            page.insert_image(page.rect, stream=image)
            page.insert_font(fontname="OCRUnicode", fontfile=fontfile)
            for block in recognized.blocks:
                text = block.normalized_text or block.original_text
                if block.bbox and text:
                    box = fitz.Rect(
                        block.bbox.x1 * width,
                        block.bbox.y1 * height,
                        block.bbox.x2 * width,
                        block.bbox.y2 * height,
                    )
                    page.insert_textbox(
                        box,
                        text,
                        fontname="OCRUnicode",
                        fontsize=max(3, min(12, box.height * 0.7)),
                        render_mode=3,
                        overlay=True,
                    )
        data = output.tobytes(deflate=True)
        output.close()
        return data
