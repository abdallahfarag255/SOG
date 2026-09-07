import os
import sys
import threading
import uuid
from datetime import date, timedelta

from dotenv import load_dotenv
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

load_dotenv(os.path.join(BASE_DIR, ".env"))

# We run several tesseract.exe processes at once (OCR passes + digit
# recognition). Tesseract's own internal multithreading then oversubscribes
# the CPU and makes recognition mildly nondeterministic under that
# concurrent load - the same image can read correctly in isolation but
# differently when several passes race together. Capping each process to
# one internal thread removes that contention.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from config import Config
from digit_recognizer import DigitRecognizer
from excel_exporter import RidersExcelExporter
from models import ImageAnalysis
from ocr_engine import OCREngine
from ocr_job_store import OCRJobStore
from rider_service import ArabicDateFormatter, ImageUploadValidator, RiderService
from version import APP_VERSION
from sheets_repository import GoogleSheetsRepository
from supabase_repository import (
    DigitTemplateRepository,
    ExtractedImageRepository,
    RiderStatsRepository,
)

config = Config()


def _resolve_tesseract_cmd() -> str:
    if config.tesseract_cmd and os.path.isfile(config.tesseract_cmd):
        return config.tesseract_cmd
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "tesseract_bin", "tesseract.exe")
        if os.path.isfile(bundled):
            return bundled
    bundled = os.path.join(BASE_DIR, "tesseract_bin", "tesseract.exe")
    if os.path.isfile(bundled):
        return bundled
    return None


tesseract_cmd = _resolve_tesseract_cmd()

sheets_repo = GoogleSheetsRepository(
    sheet_id=config.google_sheet_id,
    cache_ttl_seconds=config.sheets_cache_ttl_seconds,
    service_account_file=config.google_service_account_file,
)
stats_repo = RiderStatsRepository(config.supabase_url, config.supabase_key)
image_repo = ExtractedImageRepository(config.supabase_url, config.supabase_key)
digit_template_repo = DigitTemplateRepository(config.supabase_url, config.supabase_key)
ocr_engine = OCREngine(tesseract_cmd=tesseract_cmd)
digit_recognizer = DigitRecognizer(template_repository=digit_template_repo, tesseract_cmd=tesseract_cmd)

rider_service = RiderService(
    sheets_repo=sheets_repo,
    stats_repo=stats_repo,
    image_repo=image_repo,
    ocr_engine=ocr_engine,
    digit_recognizer=digit_recognizer,
    upload_folder=UPLOAD_FOLDER,
)

if getattr(sys, "frozen", False):
    app = Flask(__name__, template_folder=os.path.join(sys._MEIPASS, "templates"))
else:
    app = Flask(__name__)
app.secret_key = config.flask_secret_key
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ocr_jobs = OCRJobStore()


@app.route("/")
def index():
    return redirect(url_for("riders"))


MIN_ARCHIVE_DATE = date(2026, 9, 5)


def _resolve_selected_date():
    today = date.today()
    selected_str = request.args.get("date") or today.isoformat()
    selected_date = date.fromisoformat(selected_str)
    if selected_date < MIN_ARCHIVE_DATE:
        selected_date = MIN_ARCHIVE_DATE
    return selected_date, selected_date == today


@app.route("/riders")
def riders():
    selected_date, is_today = _resolve_selected_date()

    try:
        if is_today:
            rows = rider_service.get_live_riders()
        else:
            rows = rider_service.get_archived_riders(selected_date.isoformat())
    except Exception as exc:
        rows = []
        flash(f"تعذر تحميل البيانات: {exc}")

    zones = sorted({r.zone for r in rows if r.zone})

    return render_template(
        "riders.html",
        riders=rows,
        zones=zones,
        is_today=is_today,
        selected_date=selected_date.isoformat(),
        selected_date_display=ArabicDateFormatter.format(selected_date),
        prev_date=(selected_date - timedelta(days=1)).isoformat(),
        next_date=(selected_date + timedelta(days=1)).isoformat(),
        can_go_prev=selected_date > MIN_ARCHIVE_DATE,
        min_archive_date=MIN_ARCHIVE_DATE.isoformat(),
        app_version=APP_VERSION,
    )


@app.route("/riders/export")
def riders_export():
    selected_date, is_today = _resolve_selected_date()

    try:
        if is_today:
            rows = rider_service.get_live_riders()
        else:
            rows = rider_service.get_archived_riders(selected_date.isoformat())
    except Exception as exc:
        flash(f"تعذر تحميل البيانات: {exc}")
        return redirect(url_for("riders", date=selected_date.isoformat()))

    content = RidersExcelExporter.export(rows, is_today)
    filename = f"SOG-{selected_date.isoformat()}.xlsx"
    return Response(
        content,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/riders/<rider_id>/notes/save", methods=["POST"])
def rider_note_save(rider_id):
    stat_date = request.form.get("stat_date") or date.today().isoformat()
    notes = request.form.get("notes", "")
    try:
        rider_service.save_note(rider_id, stat_date, notes)
        return jsonify({"status": "ok"})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/riders/<rider_id>/photos")
def rider_photos(rider_id):
    stat_date = request.args.get("date") or date.today().isoformat()

    saved_stats = None
    try:
        saved_stats = rider_service.get_saved_stats_for(rider_id, stat_date)
    except Exception as exc:
        flash(f"تعذر تحميل البيانات المحفوظة: {exc}")

    driver_name = request.args.get("driver_name") or (saved_stats.driver_name if saved_stats else "")
    phone = request.args.get("phone") or (saved_stats.phone if saved_stats else "")
    if not driver_name:
        rider = rider_service.find_rider(rider_id)
        driver_name = rider.driver_name if rider else ""
        phone = rider.phone if rider else ""

    display_stats = {
        "complete_hours": request.args.get("complete_hours") or (saved_stats.complete_hours if saved_stats else ""),
        "complete_order": request.args.get("complete_order") or (saved_stats.complete_order if saved_stats else ""),
        "installments": request.args.get("installments") or (saved_stats.installments if saved_stats else ""),
        "wallet": request.args.get("wallet") or (saved_stats.wallet if saved_stats else ""),
    }
    images = request.args.get("images", "")
    return render_template(
        "rider_photos.html",
        rider_id=rider_id,
        driver_name=driver_name,
        phone=phone,
        stats=display_stats,
        images=images,
        stat_date=stat_date,
        job_id=request.args.get("job_id", ""),
    )


def _analyze_uploaded_photos(rider_id, saved_images):
    merged_stats, saved_count, errors = rider_service.process_uploaded_photos(rider_id, saved_images)
    return {"stats": merged_stats, "saved_count": saved_count, "errors": errors}


@app.route("/riders/<rider_id>/photos/upload", methods=["POST"])
def rider_photos_upload(rider_id):
    files = [f for f in request.files.getlist("images") if f and f.filename]
    if not files:
        flash("من فضلك اختر صورة واحدة على الأقل")
        return redirect(url_for("rider_photos", rider_id=rider_id))

    driver_name = request.form.get("driver_name", "")
    phone = request.form.get("phone", "")
    stat_date = request.form.get("stat_date") or date.today().isoformat()

    saved_images = []
    for file in files:
        if not ImageUploadValidator.is_allowed(file.filename):
            flash(f"امتداد غير مدعوم: {file.filename}")
            continue
        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
        file.save(filepath)
        saved_images.append(ImageAnalysis(filename=unique_name, filepath=filepath, original_name=file.filename))

    job_id = ocr_jobs.start(lambda: _analyze_uploaded_photos(rider_id, saved_images))

    saved_filenames = [img.filename for img in saved_images]
    return redirect(url_for(
        "rider_photos",
        rider_id=rider_id,
        images=",".join(saved_filenames),
        driver_name=driver_name,
        phone=phone,
        date=stat_date,
        job_id=job_id,
    ))


@app.route("/riders/<rider_id>/photos/status/<job_id>")
def rider_photos_status(rider_id, job_id):
    return jsonify(ocr_jobs.consume(job_id))


@app.route("/riders/<rider_id>/stats/save", methods=["POST"])
def rider_stats_save(rider_id):
    complete_hours = request.form.get("complete_hours", "").strip()
    complete_order = request.form.get("complete_order", "").strip()
    installments = request.form.get("installments", "").strip()
    wallet = request.form.get("wallet", "").strip()
    images = [f for f in request.form.get("images", "").split(",") if f]
    driver_name = request.form.get("driver_name", "").strip()
    phone = request.form.get("phone", "").strip()
    stat_date = request.form.get("stat_date") or date.today().isoformat()

    try:
        rider_service.save_stats(
            rider_id, complete_hours, complete_order, installments, wallet,
            images, driver_name, phone, stat_date,
        )
        flash("تم الحفظ بنجاح")
        threading.Thread(
            target=rider_service.learn_from_images, args=(images, installments, complete_hours), daemon=True
        ).start()
    except Exception as exc:
        flash(f"فشل الحفظ: {exc}")

    return redirect(url_for("rider_photos", rider_id=rider_id, date=stat_date))


os.makedirs(UPLOAD_FOLDER, exist_ok=True)
sheets_repo.start_background_refresh()
