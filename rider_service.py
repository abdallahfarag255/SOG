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

        try:
            self._stats_repo.ensure_daily_snapshot(riders)
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
                rider.notes = stats.notes
            rider.equation, rider.equation_sign = EquationCalculator.compute(rider.wallet, rider.installments)
            result.append(rider)
        return result

    def get_archived_riders(self, stat_date: str) -> list:
        rows = self._stats_repo.get_by_date(stat_date)
        riders = []
        for s in rows:
            equation, sign = EquationCalculator.compute(s.wallet, s.installments)
            live_rider = self.find_rider(s.rider_id)
            riders.append(Rider(
                id_rider=s.rider_id,
                driver_name=s.driver_name,
                phone=s.phone,
                zone=s.zone,
                rent_remaining=live_rider.rent_remaining if live_rider else "",
                complete_hours=s.complete_hours,
                complete_order=s.complete_order,
                installments=s.installments,
                wallet=s.wallet,
                notes=s.notes,
                equation=equation,
                equation_sign=sign,
            ))
        return riders

    def find_rider(self, rider_id: str):
        return self._sheets_repo.find_rider(rider_id)

    def get_saved_stats_for(self, rider_id: str, stat_date: str):
        return self._stats_repo.get_for_rider(rider_id, stat_date)

    def save_note(self, rider_id: str, stat_date: str, notes: str) -> None:
        self._stats_repo.update_notes(rider_id, stat_date, notes)

    def get_equation_report(self, selected_dates: list, wallet_date: str) -> list:
        """For each rider active on any of selected_dates: sum their
        installments across those dates, paired against their wallet on
        wallet_date. equation = wallet - installments_sum."""
        rows = self._stats_repo.get_by_dates(selected_dates)

        riders = {}
        for row in rows:
            entry = riders.setdefault(row.rider_id, {"driver_name": row.driver_name, "installments_sum": 0.0})
            entry["installments_sum"] += self._safe_float(row.installments)
            if row.driver_name:
                entry["driver_name"] = row.driver_name

        wallet_by_id = {}
        if wallet_date:
            wallet_by_id = {r.rider_id: self._safe_float(r.wallet) for r in self._stats_repo.get_by_date(wallet_date)}

        result = []
        for rider_id, info in riders.items():
            wallet = wallet_by_id.get(rider_id, 0.0)
            result.append({
                "rider_id": rider_id,
                "driver_name": info["driver_name"],
                "installments_sum": info["installments_sum"],
                "wallet": wallet,
                "equation": wallet - info["installments_sum"],
            })
        result.sort(key=lambda r: r["driver_name"])
        return result

    @staticmethod
    def _safe_float(value: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _analyze_image(self, analysis: ImageAnalysis) -> ImageAnalysis:
        with ThreadPoolExecutor(max_workers=3) as executor:
            variants_future = executor.submit(self._ocr_engine.extract_text_variants, analysis.filepath)
            installments_future = executor.submit(self._digit_recognizer.recognize_earned_amount, analysis.filepath)
            hours_future = executor.submit(self._digit_recognizer.recognize_complete_hours, analysis.filepath)

            try:
                analysis.text_variants = variants_future.result()
            except Exception as exc:
                analysis.error = exc

            try:
                analysis.recognized_installments = installments_future.result()
            except Exception:
                analysis.recognized_installments = ""

            try:
                analysis.recognized_hours = hours_future.result()
            except Exception:
                analysis.recognized_hours = ""

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

            # Both shape-matching recognizers only ever return a value when
            # every glyph they segmented matched a known template with high
            # confidence, so they're more trustworthy than the plain-text OCR
            # guess above (which can misread a digit but still return
            # *something*, e.g. "1س 31د" instead of "11س 31د", or garble
            # non-Western numeral fonts entirely) - let them win whenever
            # they have an answer, instead of only when text OCR found
            # nothing at all.
            if analysis.recognized_installments:
                merged_stats["installments"] = analysis.recognized_installments

            if analysis.recognized_hours:
                merged_stats["complete_hours"] = analysis.recognized_hours

        return merged_stats, saved_count, errors

    def _learn_from_image(self, filename: str, installments: str, complete_hours: str) -> None:
        filepath = os.path.join(self._upload_folder, filename)
        try:
            self._digit_recognizer.learn_earned_amount(filepath, installments)
        except Exception:
            pass
        try:
            self._digit_recognizer.learn_complete_hours(filepath, complete_hours)
        except Exception:
            pass

    def learn_from_images(self, image_filenames: list, installments: str, complete_hours: str = "") -> None:
        if not image_filenames:
            return
        with ThreadPoolExecutor(max_workers=len(image_filenames)) as executor:
            list(executor.map(lambda f: self._learn_from_image(f, installments, complete_hours), image_filenames))

    def save_stats(self, rider_id: str, complete_hours: str, complete_order: str,
                   installments: str, wallet: str, image_filenames: list,
                   driver_name: str = "", phone: str = "", stat_date: str = "") -> None:
        rider = self.find_rider(rider_id)
        if not driver_name:
            driver_name = rider.driver_name if rider else ""
            phone = rider.phone if rider else ""
        if rider:
            zone = rider.zone
        else:
            # Rider not found live (e.g. briefly missing from the sheet
            # between page load and save) - keep whatever zone is already
            # stored instead of writing blank and wiping it.
            existing = self._stats_repo.get_for_rider(rider_id, stat_date or date.today().isoformat())
            zone = existing.zone if existing else ""

        stats = RiderStats(
            rider_id=rider_id,
            complete_hours=complete_hours,
            complete_order=complete_order,
            installments=installments,
            wallet=wallet,
            driver_name=driver_name,
            phone=phone,
            zone=zone,
            stat_date=stat_date,
        )
        self._stats_repo.upsert(stats)
