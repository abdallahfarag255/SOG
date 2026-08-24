import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

from models import Rider, RiderStats, ImageAnalysis


class EquationCalculator:
    @staticmethod
    def compute(wallet: str, installments: str):
        try:
            value = float(wallet) - float(installments)
        except (TypeError, ValueError):
            return "", ""
        sign = "positive" if value > 0 else ("negative" if value < 0 else "")
        return f"{value:.2f}", sign


class ArabicDateFormatter:
    WEEKDAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    MONTHS = [
        "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
        "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
    ]

    @classmethod
    def format(cls, d: date) -> str:
        return f"{cls.WEEKDAYS[d.weekday()]}، {d.day} {cls.MONTHS[d.month - 1]} {d.year}"


class ImageUploadValidator:
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}

    @classmethod
    def is_allowed(cls, filename: str) -> bool:
        return "." in filename and filename.rsplit(".", 1)[1].lower() in cls.ALLOWED_EXTENSIONS


class RiderService:
    def __init__(self, sheets_repo, stats_repo, image_repo, ocr_engine, digit_recognizer, upload_folder: str):
        self._sheets_repo = sheets_repo
        self._stats_repo = stats_repo
        self._image_repo = image_repo
        self._ocr_engine = ocr_engine
        self._digit_recognizer = digit_recognizer
        self._upload_folder = upload_folder

    def get_live_riders(self) -> list:
        riders = self._sheets_repo.get_active_riders()
        active_ids = [r.id_rider for r in riders]

        try:
            self._stats_repo.remove_stale(active_ids)
        except Exception:
            pass

        stats_by_rider = self._stats_repo.get_all_today()

        result = []
        for rider in riders:
            rider = replace(rider)
            stats = stats_by_rider.get(rider.id_rider)
            if stats:
                rider.complete_hours = stats.complete_hours
                rider.complete_order = stats.complete_order
                rider.installments = stats.installments
                rider.wallet = stats.wallet
            rider.equation, rider.equation_sign = EquationCalculator.compute(rider.wallet, rider.installments)
            result.append(rider)
        return result

    def get_archived_riders(self, stat_date: str) -> list:
        rows = self._stats_repo.get_by_date(stat_date)
        riders = []
        for s in rows:
            equation, sign = EquationCalculator.compute(s.wallet, s.installments)
            riders.append(Rider(
                id_rider=s.rider_id,
                driver_name=s.driver_name,
                phone=s.phone,
                complete_hours=s.complete_hours,
                complete_order=s.complete_order,
                installments=s.installments,
                wallet=s.wallet,
                equation=equation,
                equation_sign=sign,
            ))
        return riders

    def find_rider(self, rider_id: str):
        return self._sheets_repo.find_rider(rider_id)

    def get_saved_stats_for_today(self, rider_id: str):
        return self._stats_repo.get_for_rider_today(rider_id)

    def _analyze_image(self, analysis: ImageAnalysis) -> ImageAnalysis:
        with ThreadPoolExecutor(max_workers=2) as executor:
            variants_future = executor.submit(self._ocr_engine.extract_text_variants, analysis.filepath)
            recognized_future = executor.submit(self._digit_recognizer.recognize_earned_amount, analysis.filepath)

            try:
                analysis.text_variants = variants_future.result()
            except Exception as exc:
                analysis.error = exc

            try:
                analysis.recognized_installments = recognized_future.result()
            except Exception:
                analysis.recognized_installments = ""

        return analysis

    def process_uploaded_photos(self, rider_id: str, saved_images: list) -> tuple:
        """saved_images: list of ImageAnalysis. Returns (merged_stats dict, saved_count, errors list)."""
        from stats_parser import RiderStatsParser

        with ThreadPoolExecutor(max_workers=max(1, len(saved_images))) as executor:
            analyzed = list(executor.map(self._analyze_image, saved_images))

        merged_stats = {"complete_hours": "", "complete_order": "", "installments": "", "wallet": ""}
        saved_count = 0
        errors = []

        for analysis in analyzed:
            if analysis.error is not None:
                errors.append(f"فشل استخراج النص من {analysis.original_name}: {analysis.error}")
                continue

            try:
                self._image_repo.insert(
                    image_name=analysis.filename, extracted_text=analysis.text_variants[0], rider_id=rider_id
                )
                saved_count += 1
            except Exception as exc:
                errors.append(f"فشل الحفظ في قاعدة البيانات لصورة {analysis.original_name}: {exc}")

            parsed = RiderStatsParser.parse_from_variants(analysis.text_variants)
            for key, value in parsed.items():
                if value:
                    merged_stats[key] = value

            if not merged_stats["installments"] and analysis.recognized_installments:
                merged_stats["installments"] = analysis.recognized_installments

        return merged_stats, saved_count, errors

    def _learn_from_image(self, filename: str, installments: str) -> None:
        filepath = os.path.join(self._upload_folder, filename)
        try:
            self._digit_recognizer.learn_earned_amount(filepath, installments)
        except Exception:
            pass

    def learn_from_images(self, image_filenames: list, installments: str) -> None:
        if not installments or not image_filenames:
            return
        with ThreadPoolExecutor(max_workers=len(image_filenames)) as executor:
            list(executor.map(lambda f: self._learn_from_image(f, installments), image_filenames))

    def save_stats(self, rider_id: str, complete_hours: str, complete_order: str,
                   installments: str, wallet: str, image_filenames: list,
                   driver_name: str = "", phone: str = "") -> None:
        if not driver_name:
            rider = self.find_rider(rider_id)
            driver_name = rider.driver_name if rider else ""
            phone = rider.phone if rider else ""

        stats = RiderStats(
            rider_id=rider_id,
            complete_hours=complete_hours,
            complete_order=complete_order,
            installments=installments,
            wallet=wallet,
            driver_name=driver_name,
            phone=phone,
        )
        self._stats_repo.upsert(stats)
