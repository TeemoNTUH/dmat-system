"""影像前處理(架構書 5.1 影像品質前處理)。

手機拍攝紀錄單最常見的三個辨識失敗原因,在此一併處理:

1. **EXIF 方向未套用** — iOS/Android 相機把照片存成橫向 + EXIF Orientation 標記。
   視覺模型讀到的是「未旋轉」的原始像素,整張表單是躺著的,辨識率會崩掉。
2. **解析度過高** — 4000×3000 的照片送進視覺模型會被切成大量 image token,
   反而稀釋注意力且大幅拖慢推論。長邊壓到 ~2000px 對手寫辨識最划算。
3. **對比不足** — 現場光線不均、鉛筆字淺。可選的自動對比拉伸能明顯改善淺色手寫。

回傳一律轉為 JPEG(品質 92),避免 HEIC/PNG alpha 等格式在下游引擎踩雷。
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from . import config

logger = logging.getLogger(__name__)


@dataclass
class PreprocessInfo:
    """前處理過程摘要,回傳給呼叫端供除錯(哪一步動了什麼)。"""

    original_size: tuple[int, int] = (0, 0)
    final_size: tuple[int, int] = (0, 0)
    original_bytes: int = 0
    final_bytes: int = 0
    exif_transposed: bool = False
    resized: bool = False
    enhanced: bool = False
    original_format: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "originalSize": f"{self.original_size[0]}x{self.original_size[1]}",
            "finalSize": f"{self.final_size[0]}x{self.final_size[1]}",
            "originalBytes": self.original_bytes,
            "finalBytes": self.final_bytes,
            "exifTransposed": self.exif_transposed,
            "resized": self.resized,
            "enhanced": self.enhanced,
            "originalFormat": self.original_format,
            "notes": self.notes,
        }


def prepare_image(image_bytes: bytes) -> tuple[bytes, str, PreprocessInfo]:
    """回傳 (處理後位元組, content_type, 前處理摘要)。

    前處理失敗時退回原始位元組 — 寧可讓模型拿到未處理的影像,
    也不要因為前處理例外導致整筆辨識失敗(架構書 5.3 降級原則)。
    """
    info = PreprocessInfo(original_bytes=len(image_bytes))

    if not config.PREPROCESS_ENABLED:
        info.notes.append("前處理已由組態關閉(DMAT_PREPROCESS=0)")
        return image_bytes, "image/jpeg", info

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            info.original_format = im.format
            info.original_size = im.size

            # 1. 套用 EXIF Orientation(手機直立拍攝的關鍵一步)
            before = im.size
            im = ImageOps.exif_transpose(im)
            info.exif_transposed = im.size != before or _has_orientation_tag(image_bytes)

            # 2. 去掉 alpha / palette,統一為 RGB
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            elif im.mode == "L":
                im = im.convert("RGB")

            # 3. 長邊縮放
            max_edge = config.PREPROCESS_MAX_EDGE
            if max_edge > 0 and max(im.size) > max_edge:
                scale = max_edge / max(im.size)
                new_size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
                im = im.resize(new_size, Image.LANCZOS)
                info.resized = True

            # 4. 可選:自動對比 + 銳化(淺色手寫、光線不均時有感)
            if config.PREPROCESS_ENHANCE:
                im = ImageOps.autocontrast(im, cutoff=1)
                im = ImageEnhance.Sharpness(im).enhance(1.4)
                info.enhanced = True

            info.final_size = im.size
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=config.PREPROCESS_JPEG_QUALITY, optimize=True)
            out = buf.getvalue()

        info.final_bytes = len(out)
        return out, "image/jpeg", info

    except Exception as exc:  # noqa: BLE001 — 前處理不得讓辨識整體失敗
        logger.warning("影像前處理失敗,改用原始影像:%s", exc)
        info.notes.append(f"前處理失敗,已改用原始影像:{exc}")
        return image_bytes, "image/jpeg", info


def _has_orientation_tag(image_bytes: bytes) -> bool:
    """判斷原檔是否帶 EXIF Orientation(即使旋轉後尺寸沒變也要記錄下來)。"""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            exif = im.getexif()
            return bool(exif) and exif.get(274, 1) != 1
    except Exception:  # noqa: BLE001
        return False
