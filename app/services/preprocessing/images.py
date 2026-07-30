import io

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def preprocess(image_bytes: bytes, mode: str) -> tuple[bytes, dict]:
    if mode == "none":
        return image_bytes, {"mode": "none", "operations": []}
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    operations = []
    array = np.asarray(image)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    coords = np.column_stack(np.where(gray < 245))
    angle = 0.0
    if len(coords) > 100:
        angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
        angle = -(90 + angle) if angle < -45 else -angle
        if abs(angle) < 5 and abs(angle) > 0.15:
            center = (array.shape[1] / 2, array.shape[0] / 2)
            matrix = cv2.getRotationMatrix2D(center, angle, 1)
            array = cv2.warpAffine(
                array, matrix, (array.shape[1], array.shape[0]), borderMode=cv2.BORDER_REPLICATE
            )
            image = Image.fromarray(array)
            operations.append("deskew")
    image = ImageEnhance.Contrast(image).enhance(1.08)
    operations.append("contrast")
    if mode in {"enhanced", "auto"}:
        image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=3))
        operations.append("sharpen")
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue(), {"mode": mode, "operations": operations, "deskew_angle": round(angle, 3)}
