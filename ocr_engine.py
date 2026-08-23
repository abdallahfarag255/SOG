import pytesseract
from PIL import Image, ImageOps


class ImagePreprocessor:
    MAX_SOURCE_DIMENSION = 1100

    @staticmethod
    def grayscale_upscale(image_path: str, scale: int) -> Image.Image:
        image = Image.open(image_path)
        gray = ImageOps.grayscale(image)
        w, h = gray.size
        longest = max(w, h)
        if longest > ImagePreprocessor.MAX_SOURCE_DIMENSION:
            factor = ImagePreprocessor.MAX_SOURCE_DIMENSION / longest
            w, h = max(1, round(w * factor)), max(1, round(h * factor))
            gray = gray.resize((w, h), Image.LANCZOS)
        return gray.resize((w * scale, h * scale), Image.LANCZOS)


class OCREngine:
    CONFIGS = [(2, 6), (2, 11)]

    def __init__(self, tesseract_cmd: str = None, lang: str = "ara+eng"):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self._lang = lang

    def _run(self, image_path: str, scale: int, psm: int) -> str:
        image = ImagePreprocessor.grayscale_upscale(image_path, scale)
        return pytesseract.image_to_string(image, lang=self._lang, config=f"--psm {psm} --oem 1").strip()

    def extract_text_variants(self, image_path: str) -> list:
        return [self._run(image_path, scale, psm) for scale, psm in self.CONFIGS]
