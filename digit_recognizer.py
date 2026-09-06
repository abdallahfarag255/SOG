import base64
import re
import threading

import numpy as np
import pytesseract
from pytesseract import Output
from PIL import Image, ImageOps


class DigitRecognizer:
    CANVAS_SIZE = (40, 60)
    MATCH_THRESHOLD = 0.72
    MAX_TEMPLATES_PER_CLASS = 40
    DIGIT_CLASSES = [str(d) for d in range(10)]
    SEPARATOR_CLASSES = ["THOUSANDS_SEP", "DECIMAL_SEP", "HOUR_MARKER", "MINUTE_MARKER"]
    ALL_CLASSES = DIGIT_CLASSES + SEPARATOR_CLASSES
    EARNED_LABEL_TOKENS = ["إجمالي", "المبالغ", "المكتسبة"]
    # "ساعات" alone is ambiguous (it also appears in "عروض ساعات الذروة" /
    # peak-hour bonuses); "التوصيل" only appears in the delivery-hours label.
    HOURS_LABEL_TOKENS = ["التوصيل"]
    HOURS_PATTERN = re.compile(r"^(\d+)\s*س\s*(\d+)\s*د$")
    MAX_SOURCE_DIMENSION = 1600

    def __init__(self, template_repository, tesseract_cmd: str = None, lang: str = "ara+eng"):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self._repo = template_repository
        self._lang = lang
        self._templates_cache = None
        self._cache_lock = threading.Lock()

    def recognize_earned_amount(self, image_path: str) -> str:
        crop = self._locate_value_line(image_path, self.EARNED_LABEL_TOKENS)
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

        crop = self._locate_value_line(image_path, self.EARNED_LABEL_TOKENS)
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

    def recognize_complete_hours(self, image_path: str) -> str:
        crop = self._locate_value_line(image_path, self.HOURS_LABEL_TOKENS)
        if crop is None:
            return ""

        labels = []
        for glyph in self._segment_glyphs(crop):
            canvas = self._to_canvas(glyph)
            label, score = self._classify(canvas)
            if label is None or score < self.MATCH_THRESHOLD:
                return ""
            labels.append(label)

        return self._format_hours(labels)

    def learn_complete_hours(self, image_path: str, confirmed_value: str) -> bool:
        match = self.HOURS_PATTERN.match(confirmed_value.strip())
        if not match:
            return False
        hours, minutes = match.group(1), match.group(2)

        crop = self._locate_value_line(image_path, self.HOURS_LABEL_TOKENS)
        if crop is None:
            return False

        glyphs = self._segment_glyphs(crop)
        expected = list(hours) + ["HOUR_MARKER"] + list(minutes) + ["MINUTE_MARKER"]

        if len(glyphs) < len(expected):
            return False

        glyphs = glyphs[-len(expected):]

        for glyph, label in zip(glyphs, expected):
            self._save_template(self._to_canvas(glyph), label)

        return True

    @classmethod
    def _format_hours(cls, labels: list) -> str:
        if "HOUR_MARKER" not in labels or "MINUTE_MARKER" not in labels:
            return ""
        h_idx = labels.index("HOUR_MARKER")
        m_idx = labels.index("MINUTE_MARKER")
        if m_idx < h_idx:
            return ""
        hour_digits = labels[:h_idx]
        minute_digits = labels[h_idx + 1: m_idx]
        if not hour_digits or not minute_digits:
            return ""
        if any(d not in cls.DIGIT_CLASSES for d in hour_digits + minute_digits):
            return ""
        return f"{''.join(hour_digits)}س {''.join(minute_digits)}د"

    def _locate_value_line(self, image_path: str, label_tokens: list, scale: int = 2):
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

        label_idx = None
        for i, text in enumerate(data["text"]):
            if text.strip() in label_tokens:
                label_idx = i
                break
        if label_idx is None:
            return None

        label_block = data["block_num"][label_idx]
        label_left = data["left"][label_idx]
        label_top = data["top"][label_idx]
        label_bottom = label_top + data["height"][label_idx]
        label_center_x = label_left + data["width"][label_idx] / 2

        # Group words into per-block bounding boxes. Two stat pills sitting
        # side by side on the same row (e.g. "avg per hour" and "delivery
        # hours") can end up as adjacent block numbers, so "next block" isn't
        # reliably "the value below this label" - instead, pick whichever
        # other block sits below the label and is horizontally aligned with it.
        blocks = {}
        for i in range(len(data["text"])):
            if not data["text"][i].strip():
                continue
            b = data["block_num"][i]
            l, t, w_, h_ = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            box = blocks.setdefault(b, [l, t, l + w_, t + h_])
            box[0] = min(box[0], l)
            box[1] = min(box[1], t)
            box[2] = max(box[2], l + w_)
            box[3] = max(box[3], t + h_)

        max_gap = 100 * scale
        candidates = []
        for b, (l, t, r, btm) in blocks.items():
            if b == label_block:
                continue
            gap = t - label_bottom
            if gap < -10 or gap > max_gap:
                continue
            h_offset = abs((l + r) / 2 - label_center_x)
            candidates.append((h_offset, gap, (l, t, r, btm)))

        if not candidates:
            return None
        candidates.sort(key=lambda c: (c[0], c[1]))
        lefts_box = candidates[0][2]

        box = (max(0, lefts_box[0] - 20), max(0, lefts_box[1] - 15), lefts_box[2] + 20, lefts_box[3] + 15)
        return self._normalize_polarity(upscaled.crop(box))

    @staticmethod
    def _normalize_polarity(crop_img: Image.Image) -> Image.Image:
        """Glyph segmentation/canvas logic below assumes dark text on a light
        background. Some UI value boxes (e.g. the hours pill) are the
        opposite - light text on a dark background - which would otherwise
        make the whole box look like one solid ink blob. Detect that from
        the crop's border pixels (background, not text) and invert if needed."""
        gray = crop_img.convert("L")
        arr = np.array(gray)
        border = np.concatenate([arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]])
        if border.mean() < 128:
            return ImageOps.invert(gray)
        return gray

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
        # recognize_earned_amount and recognize_complete_hours run
        # concurrently (see RiderService._analyze_image), both hitting this
        # on first use. Without the lock, one thread could see the cache
        # dict already assigned (non-None) while another thread is still in
        # the middle of populating it, and would silently match against an
        # empty template set - i.e. every glyph reads as "no match".
        if self._templates_cache is not None:
            return
        with self._cache_lock:
            if self._templates_cache is not None:
                return
            cache = {label: [] for label in self.ALL_CLASSES}
            for label, rows in self._repo.get_all().items():
                cache.setdefault(label, [])
                for row in rows:
                    cache[label].append({
                        "id": row["id"],
                        "canvas": self._str_to_canvas(row["canvas_data"]),
                    })
            self._templates_cache = cache

    def _save_template(self, canvas: np.ndarray, label: str) -> None:
        self._ensure_cache()
        with self._cache_lock:
            bucket = self._templates_cache.setdefault(label, [])
            if len(bucket) >= self.MAX_TEMPLATES_PER_CLASS:
                oldest = bucket.pop(0)
                self._repo.delete(oldest["id"])
            row = self._repo.insert(label, self._canvas_to_str(canvas))
            bucket.append({"id": row.get("id"), "canvas": canvas})

    def _classify(self, glyph_canvas: np.ndarray):
        self._ensure_cache()
        best_label, best_score = None, 0.0
        with self._cache_lock:
            templates_by_label = {label: list(self._templates_cache.get(label, [])) for label in self.ALL_CLASSES}
        for label in self.ALL_CLASSES:
            for template in templates_by_label[label]:
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
