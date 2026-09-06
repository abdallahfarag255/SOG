from concurrent.futures import ThreadPoolExecutor

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


class ImagePreprocessor:
    MAX_SOURCE_DIMENSION = 1600

    @staticmethod
    def grayscale_upscale(image_path: str, scale: int, invert: bool = False, sharpen: bool = False) -> Image.Image:
        image = Image.open(image_path)
        gray = ImageOps.grayscale(image)
        if invert:
            gray = ImageOps.invert(gray)
        w, h = gray.size
        longest = max(w, h)
        if longest > ImagePreprocessor.MAX_SOURCE_DIMENSION:
            factor = ImagePreprocessor.MAX_SOURCE_DIMENSION / longest
            w, h = max(1, round(w * factor)), max(1, round(h * factor))
            gray = gray.resize((w, h), Image.LANCZOS)
        upscaled = gray.resize((w * scale, h * scale), Image.LANCZOS)

        if sharpen:
            # WhatsApp heavily re-compresses images sent as "photos" (small
            # resolution + JPEG artifacts), which blurs digit edges. A mild
            # contrast boost + unsharp mask can recover some of that edge
            # definition — but it can just as easily distort an already-clean
            # image, so it only runs as its own extra pass, never replacing
            # the plain passes that already work well on most photos.
            upscaled = ImageEnhance.Contrast(upscaled).enhance(1.4)
            upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
        return upscaled


class OCREngine:
    # (scale, psm, invert, sharpen)
    # psm 6 treats the whole screenshot as one uniform text block, which
    # merges side-by-side stat boxes (e.g. "hours" and "avg per hour" pills
    # sitting in the same row) into a single scrambled line. psm 3 (full
    # automatic page segmentation) detects them as separate blocks instead.
    # The inverted pass helps read light-background UI elements (pill/badge
    # buttons) embedded in an otherwise dark-background screenshot. The
    # sharpened pass targets heavily-compressed WhatsApp "photo" uploads.
    CONFIGS = [(2, 6, False, False), (3, 11, False, False), (2, 3, False, False),
               (2, 6, True, False), (3, 11, False, True)]

    def __init__(self, tesseract_cmd: str = None, lang: str = "ara+eng"):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self._lang = lang

    def _run(self, image_path: str, scale: int, psm: int, invert: bool, sharpen: bool) -> str:
        image = ImagePreprocessor.grayscale_upscale(image_path, scale, invert, sharpen)
        return pytesseract.image_to_string(image, lang=self._lang, config=f"--psm {psm} --oem 1").strip()

    def extract_text_variants(self, image_path: str) -> list:
        with ThreadPoolExecutor(max_workers=len(self.CONFIGS)) as executor:
            futures = [
                executor.submit(self._run, image_path, scale, psm, invert, sharpen)
                for scale, psm, invert, sharpen in self.CONFIGS
            ]
            return [f.result() for f in futures]
