import os


class Config:
    def __init__(self):
        # على الاستضافة: GOOGLE_SERVICE_ACCOUNT_JSON (محتوى الملف كامل كـ env var)
        # محليًا: GOOGLE_SERVICE_ACCOUNT_FILE (مسار الملف على الجهاز)
        self.google_service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        self.google_service_account_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        self.google_sheet_id = os.environ["GOOGLE_SHEET_ID"]
        self.supabase_url = os.environ["SUPABASE_URL"]
        self.supabase_key = os.environ["SUPABASE_KEY"]
        self.tesseract_cmd = os.environ.get("TESSERACT_CMD")
        self.flask_secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
        self.sheets_cache_ttl_seconds = int(os.environ.get("SHEETS_CACHE_TTL_SECONDS", "60"))
