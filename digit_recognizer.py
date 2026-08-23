import base64
import re

import numpy as np
import pytesseract
from pytesseract import Output
from PIL import Image, ImageOps


class DigitRecognizer:
    CANVAS_SIZE = (40, 60)
    MATCH_THRESHOLD = 0.72
    MAX_TEMPLATES_PER_CLASS = 40
    DIGIT_CLASSES = [str(d) for d in range(10)]
    SEPARATOR_CLASSES = ["THOUSANDS_SEP", "DECIMAL_SEP"]
    ALL_CLASSES = DIGIT_CLASSES + SEPARATOR_CLASSES
    EARNED_LABEL_TOKENS = ["إجمالي", "المبالغ", "المكتسبة"]
    MAX_SOURCE_DIMENSION = 900

    def __init__(self, template_repository, tesseract_cmd: str = None, lang: str = "ara+eng"):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self._repo = template_repository
        self._lang = lang
        self._templates_cache = None

    def recognize_earned_amount(self, image_path: str) -> str:
        crop = self._locate_value_line(image_path)
        if crop is None:
            return ""

        digits = []
        for glyph in self._segment_glyphs(crop):
            canvas = self._to_canvas(glyph)
            label, score = self._classify(canvas)
            if label in self.DIGIT_CLASSES and score >= self.MATCH_THRESHOLD:
                digits.append(label)

        if len(digits) < 3:
            return ""

        return "".join(digits[:-2]) + "." + "".join(digits[-2:])

    def learn_earned_amount(self, image_path: str, confirmed_value: str) -> bool:
        confirmed_value = confirmed_value.strip()
        if not re.match(r"^\d+(\.\d+)?$", confirmed_value):
            return False

        crop = self._locate_value_line(image_path)
        if crop is None:
            return False

        glyphs = self._segment_glyphs(crop)
        expected = self._expected_label_sequence(confirmed_value)

        if len(glyphs) < len(expected):
            return False

        glyphs = glyphs[-len(expected):]

        for glyph, label in zip(glyphs, expected):
            self._save_template(self._to_canvas(glyph), label)

        return True

    def _locate_value_line(self, image_path: str, scale: int = 2):
        image = Image.open(image_path)
        gray = ImageOps.grayscale(image)
        w, h = gray.size
        longest = max(w, h)
        if longest > self.MAX_SOURCE_DIMENSION:
            factor = self.MAX_SOURCE_DIMENSION / longest
            w, h = max(1, round(w * factor)), max(1, round(h * factor))
            gray = gray.resize((w, h), Image.LANCZOS)
        upscaled = gray.resize((w * scale, h * scale), Image.LANCZOS)

        data = pytesseract.image_to_data(upscaled, lang=self._lang, config="--psm 11 --oem 1", output_type=Output.DICT)

        label_block = None
        for i, text in enumerate(data["text"]):
            if text.strip() in self.EARNED_LABEL_TOKENS:
                label_block = data["block_num"][i]
                break
        if label_block is None:
            return None

        value_block = label_block + 1
        lefts, tops, rights, bottoms = [], [], [], []
        for i in range(len(data["text"])):
            if data["text"][i].strip() and data["block_num"][i] == value_block:
                l, t, ww, hh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                lefts.append(l)
                tops.append(t)
                rights.append(l + ww)
                bottoms.append(t + hh)

        if not lefts:
            return None

        box = (max(0, min(lefts) - 20), max(0, min(tops) - 15), max(rights) + 20, max(bottoms) + 15)
        return upscaled.crop(box)

    @staticmethod
    def _segment_glyphs(crop_img: Image.Image) -> list:
        bw = np.array(crop_img) < 140
        col_has_ink = bw.any(axis=0)

        segments = []
        in_seg = False
        start = 0
        for x, has in enumerate(col_has_ink):
            if has and not in_seg:
                in_seg = True
                start = x
            elif not has and in_seg:
                in_seg = False
                segments.append((start, x))
        if in_seg:
            segments.append((start, len(col_has_ink)))

        return [crop_img.crop((x0, 0, x1, crop_img.height)) for x0, x1 in segments]

    def _to_canvas(self, glyph_img: Image.Image) -> np.ndarray:
        bbox = ImageOps.invert(glyph_img.convert("L")).getbbox()
        if bbox:
            glyph_img = glyph_img.crop(bbox)
        resized = glyph_img.convert("L").resize(self.CANVAS_SIZE, Image.LANCZOS)
        return np.array(resized) < 140

    def _ensure_cache(self) -> None:
        if self._templates_cache is not None:
            return
        self._templates_cache = {label: [] for label in self.ALL_CLASSES}
        for label, rows in self._repo.get_all().items():
            self._templates_cache.setdefault(label, [])
            for row in rows:
                self._templates_cache[label].append({
                    "id": row["id"],
                    "canvas": self._str_to_canvas(row["canvas_data"]),
                })

    def _save_template(self, canvas: np.ndarray, label: str) -> None:
        self._ensure_cache()
        bucket = self._templates_cache.setdefault(label, [])
        if len(bucket) >= self.MAX_TEMPLATES_PER_CLASS:
            oldest = bucket.pop(0)
            self._repo.delete(oldest["id"])
        row = self._repo.insert(label, self._canvas_to_str(canvas))
        bucket.append({"id": row.get("id"), "canvas": canvas})

    def _classify(self, glyph_canvas: np.ndarray):
        self._ensure_cache()
        best_label, best_score = None, 0.0
        for label in self.ALL_CLASSES:
            for template in self._templates_cache.get(label, []):
                canvas = template["canvas"]
                union = np.logical_or(glyph_canvas, canvas).sum()
                if union == 0:
                    continue
                intersection = np.logical_and(glyph_canvas, canvas).sum()
                score = intersection / union
                if score > best_score:
                    best_score = score
                    best_label = label
        return best_label, best_score

    def _canvas_to_str(self, canvas: np.ndarray) -> str:
        packed = np.packbits(canvas.astype(np.uint8))
        return base64.b64encode(packed.tobytes()).decode("ascii")

    def _str_to_canvas(self, data: str) -> np.ndarray:
        width, height = self.CANVAS_SIZE
        packed = np.frombuffer(base64.b64decode(data), dtype=np.uint8)
        bits = np.unpackbits(packed)[: width * height]
        return bits.reshape((height, width)).astype(bool)

    @staticmethod
    def _expected_label_sequence(confirmed_value: str) -> list:
        if "." in confirmed_value:
            int_part, dec_part = confirmed_value.split(".", 1)
        else:
            int_part, dec_part = confirmed_value, ""

        int_part = int_part or "0"
        digits = list(int_part)
        group_positions = set()
        count = 0
        for i in range(len(digits) - 1, -1, -1):
            count += 1
            if count % 3 == 0 and i != 0:
                group_positions.add(i)

        labels = []
        for i, d in enumerate(digits):
            labels.append(d)
            if i in group_positions:
                labels.append("THOUSANDS_SEP")

        if dec_part:
            labels.append("DECIMAL_SEP")
            labels.extend(list(dec_part))

        return labels
