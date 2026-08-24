import os
import sys
import threading
import uuid
from datetime import date, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

load_dotenv(os.path.join(BASE_DIR, ".env"))

from auth_service import AuthService
from config import Config
from digit_recognizer import DigitRecognizer
from models import ImageAnalysis
from ocr_engine import OCREngine
from ocr_job_store import OCRJobStore
from rider_service import ArabicDateFormatter, ImageUploadValidator, RiderService
from sheets_repository import GoogleSheetsRepository
from supabase_repository import (
    DigitTemplateRepository,
    ExtractedImageRepository,
    RiderStatsRepository,
    UserRepository,
)

config = Config()

sheets_repo = GoogleSheetsRepository(
    sheet_id=config.google_sheet_id,
    cache_ttl_seconds=config.sheets_cache_ttl_seconds,
    service_account_file=config.google_service_account_file,
)
stats_repo = RiderStatsRepository(config.supabase_url, config.supabase_key)
image_repo = ExtractedImageRepository(config.supabase_url, config.supabase_key)
user_repo = UserRepository(config.supabase_url, config.supabase_key)
digit_template_repo = DigitTemplateRepository(config.supabase_url, config.supabase_key)
ocr_engine = OCREngine(tesseract_cmd=config.tesseract_cmd)
digit_recognizer = DigitRecognizer(template_repository=digit_template_repo, tesseract_cmd=config.tesseract_cmd)

rider_service = RiderService(
    sheets_repo=sheets_repo,
    stats_repo=stats_repo,
    image_repo=image_repo,
    ocr_engine=ocr_engine,
    digit_recognizer=digit_recognizer,
    upload_folder=UPLOAD_FOLDER,
)
auth_service = AuthService(user_repo)

if getattr(sys, "frozen", False):
    app = Flask(__name__, template_folder=os.path.join(sys._MEIPASS, "templates"))
else:
    app = Flask(__name__)
app.secret_key = config.flask_secret_key
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ocr_jobs = OCRJobStore()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if auth_service.verify(username, password):
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("riders"))
        error = "اسم المستخدم أو كلمة السر غير صحيحة"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return redirect(url_for("riders"))


@app.route("/riders")
@login_required
def riders():
    today = date.today()
    selected_str = request.args.get("date") or today.isoformat()
    selected_date = date.fromisoformat(selected_str)
    is_today = selected_date == today

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
        selected_date_display=ArabicDateFormatter.format(selected_date),
        prev_date=(selected_date - timedelta(days=1)).isoformat(),
        next_date=(selected_date + timedelta(days=1)).isoformat(),
    )


@app.route("/riders/<rider_id>/photos")
@login_required
def rider_photos(rider_id):
    saved_stats = None
    try:
        saved_stats = rider_service.get_saved_stats_for_today(rider_id)
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
        job_id=request.args.get("job_id", ""),
    )


def _analyze_uploaded_photos(rider_id, saved_images):
    merged_stats, saved_count, errors = rider_service.process_uploaded_photos(rider_id, saved_images)
    return {"stats": merged_stats, "saved_count": saved_count, "errors": errors}


@app.route("/riders/<rider_id>/photos/upload", methods=["POST"])
@login_required
def rider_photos_upload(rider_id):
    files = [f for f in request.files.getlist("images") if f and f.filename]
    if not files:
        flash("من فضلك اختر صورة واحدة على الأقل")
        return redirect(url_for("rider_photos", rider_id=rider_id))

    driver_name = request.form.get("driver_name", "")
    phone = request.form.get("phone", "")

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
        job_id=job_id,
    ))


@app.route("/riders/<rider_id>/photos/status/<job_id>")
@login_required
def rider_photos_status(rider_id, job_id):
    return jsonify(ocr_jobs.consume(job_id))


@app.route("/riders/<rider_id>/stats/save", methods=["POST"])
@login_required
def rider_stats_save(rider_id):
    complete_hours = request.form.get("complete_hours", "").strip()
    complete_order = request.form.get("complete_order", "").strip()
    installments = request.form.get("installments", "").strip()
    wallet = request.form.get("wallet", "").strip()
    images = [f for f in request.form.get("images", "").split(",") if f]
    driver_name = request.form.get("driver_name", "").strip()
    phone = request.form.get("phone", "").strip()

    try:
        rider_service.save_stats(
            rider_id, complete_hours, complete_order, installments, wallet,
            images, driver_name, phone,
        )
        flash("تم الحفظ بنجاح")
        threading.Thread(
            target=rider_service.learn_from_images, args=(images, installments), daemon=True
        ).start()
    except Exception as exc:
        flash(f"فشل الحفظ: {exc}")

    return redirect(url_for("rider_photos", rider_id=rider_id))


os.makedirs(UPLOAD_FOLDER, exist_ok=True)
sheets_repo.start_background_refresh()
