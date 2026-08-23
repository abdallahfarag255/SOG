import re


class RiderStatsParser:
    ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

    HOURS_LABEL = "ساعات التوصيل"
    ORDER_LABEL = "مكتمل"
    EARNED_LABEL = "إجمالي المبالغ المكتسبة"
    WALLET_LABEL = "الرصيد الحالي"

    @classmethod
    def _normalize(cls, text: str) -> str:
        text = text.translate(cls.ARABIC_DIGITS)
        text = text.replace("٫", ".").replace("٬", ",")
        return text

    @staticmethod
    def _segment_after(text: str, label: str, window: int) -> str:
        idx = text.find(label)
        if idx == -1:
            return ""
        return text[idx + len(label): idx + len(label) + window]

    @classmethod
    def _find_decimal_amount(cls, text: str, label: str, window: int) -> str:
        segment = cls._segment_after(text, label, window)
        if not segment:
            return ""
        match = re.search(r"\d[\d,]*\.\d{1,2}\b", segment)
        return match.group(0).replace(",", "") if match else ""

    @classmethod
    def _find_any_number(cls, text: str, label: str, window: int) -> str:
        segment = cls._segment_after(text, label, window)
        if not segment:
            return ""
        match = re.search(r"\d[\d,]*\.\d+|\d[\d,]*", segment)
        return match.group(0).replace(",", "") if match else ""

    @classmethod
    def _extract_hours(cls, text: str) -> str:
        idx = text.find(cls.HOURS_LABEL)
        if idx == -1:
            return ""
        segment = text[idx: idx + 40]
        match = re.search(r"(\d+)\s*س\s*(\d+)\s*د", segment)
        return f"{match.group(1)}س {match.group(2)}د" if match else ""

    @classmethod
    def _extract_order(cls, text: str) -> str:
        idx = text.find(cls.ORDER_LABEL)
        if idx == -1:
            return ""
        segment = text[idx: idx + 15]
        match = re.search(r"\d+", segment)
        return match.group(0) if match else ""

    @classmethod
    def _extract_amount_field(cls, texts: list, label: str, window: int = 50) -> str:
        for raw_text in texts:
            text = cls._normalize(raw_text)
            value = cls._find_decimal_amount(text, label, window)
            if value:
                return value

        for raw_text in texts:
            text = cls._normalize(raw_text)
            value = cls._find_any_number(text, label, window)
            if value:
                return value

        return ""

    @classmethod
    def parse_from_variants(cls, texts: list) -> dict:
        result = {"complete_hours": "", "complete_order": "", "installments": "", "wallet": ""}

        for raw_text in texts:
            text = cls._normalize(raw_text)
            if not result["complete_hours"]:
                result["complete_hours"] = cls._extract_hours(text)
            if not result["complete_order"]:
                result["complete_order"] = cls._extract_order(text)

        result["installments"] = cls._extract_amount_field(texts, cls.EARNED_LABEL)
        result["wallet"] = cls._extract_amount_field(texts, cls.WALLET_LABEL)

        return result
