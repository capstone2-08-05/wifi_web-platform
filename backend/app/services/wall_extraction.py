from pathlib import Path

import cv2
import numpy as np

from app.core.settings import MASK_DIR


def run_rule_based_wall_extraction(image_path: Path) -> Path:
    MASK_DIR.mkdir(parents=True, exist_ok=True)

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Failed to read image: {image_path}")

    blur = cv2.GaussianBlur(img, (3, 3), 0)
    bw = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 5
    )

    kernel_close = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel_close, iterations=2)

    kernel_open = np.ones((2, 2), np.uint8)
    cleaned = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel_open, iterations=1)

    output = MASK_DIR / f"{image_path.stem}_rule_mask.png"
    cv2.imwrite(str(output), cleaned)
    return output
