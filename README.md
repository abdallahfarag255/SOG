# SOG Monitoring — نظام متابعة الراكبين

نظام بيقرا بيانات الراكبين الـ Active من Google Sheet، وبيدّي إمكانية رفع صور (لقطات شاشة من تطبيق طلبات) واستخراج بياناتها بالـ OCR، وحفظها يوميًا في Supabase.

## بنية المشروع (OOP)

```
config.py              # إعدادات المشروع (متغيرات البيئة)
models.py               # Rider, RiderStats, ImageAnalysis (dataclasses)
sheets_repository.py    # GoogleSheetsRepository — قراءة الشيت + كاش 60 ثانية + تحديث خلفي تلقائي
supabase_repository.py  # ExtractedImageRepository, RiderStatsRepository, UserRepository
auth_service.py          # AuthService — التحقق من تسجيل الدخول
ocr_engine.py            # OCREngine, ImagePreprocessor — استخراج النص بالتوازي
stats_parser.py          # RiderStatsParser — استخراج الأرقام من النص
digit_recognizer.py      # DigitRecognizer — تعرّف ذاتي على أرقام عربية بخط مخصص
rider_service.py         # RiderService — طبقة الأعمال اللي بتجمع كل حاجة فوق
app.py                    # Flask routes (طبقة تحكم رفيعة بس)
desktop.py                # نقطة تشغيل التطبيق كـ Desktop App (pywebview + waitress)
```

## 1. تثبيت المتطلبات

```powershell
cd C:\Users\Abdal\ocr-sheets-app
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. تثبيت Tesseract OCR (البرنامج نفسه، مش مكتبة بايثون)

- نزّل النسخة لويندوز من: https://github.com/UB-Mannheim/tesseract/wiki
- أثناء التثبيت اختار حزمة اللغة العربية (Arabic).
- لو مش هيتحط في PATH، خد مسار `tesseract.exe` وحطه في `.env` تحت `TESSERACT_CMD`.

## 3. إعداد Google Sheets

1. فعّل **Google Sheets API** في Google Cloud Console.
2. حط ملف الـ Service Account JSON في مجلد المشروع باسم `service_account.json`.
3. شارك الشيت مع إيميل الـ service account بصلاحية **Viewer** على الأقل (النظام بيقرأ بس، مش بيكتب في الشيت).
4. خد `Sheet ID` من رابط الشيت.

## 4. إعداد Supabase

نفّذ محتوى `supabase_schema.sql` كامل في **SQL Editor** بتاع Supabase — بيفتح 3 جداول:
- `extracted_data`: أرشيف كل صورة اتعملها OCR.
- `rider_stats`: بيانات Complete Hours / Complete Order / Installments / Wallet **مقسّمة يوميًا** (`stat_date`) — كل يوم جدول مستقل، ولما اليوم يعدي بياناته بتتقفل ومش بتتعدّل تاني.
- `users`: بيانات تسجيل الدخول (username + password مشفّرة).

خد من **Project Settings > API**: `Project URL` و `service_role key` (أو `secret key` في الواجهة الجديدة).

### إضافة مستخدم لتسجيل الدخول

بيانات الدخول متخزنة في جدول `users`، مش في `.env`. لإضافة مستخدم جديد:

```powershell
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('كلمة_السر'))"
```

خد الناتج (الهاش) والصقه في SQL Editor:

```sql
insert into users (username, password_hash) values ('اسم_المستخدم', 'الهاش_اللي_طلع');
```

## 5. ملف البيئة

```powershell
copy .env.example .env
```

املأ فيه: `GOOGLE_SERVICE_ACCOUNT_FILE`, `GOOGLE_SHEET_ID`, `SUPABASE_URL`, `SUPABASE_KEY`, `TESSERACT_CMD`.

اختياري: `SHEETS_CACHE_TTL_SECONDS` (افتراضي 60) — مدة تخزين نتيجة قراءة الشيت مؤقتًا قبل ما يعيد القراءة تاني، عشان يقلل زمن الاستجابة.

## 6. تشغيل السيستم (Desktop App)

السيستم بيشتغل كبرنامج desktop عادي على جهازك — بيستخدم معالج جهازك الكامل، وبيفضل متصل بنفس Google Sheet وSupabase.

### تشغيل مباشر (للتجربة)

```powershell
python desktop.py
```

هتفتحلك نافذة desktop عادية باسم "SOG Monitoring".

### عمل ملف .exe مستقل

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "templates;templates" --name "SOG Monitoring" desktop.py
```

الناتج هيكون في `dist\SOG Monitoring.exe`. **مهم:** لازم تحط ملفات `.env` و `service_account.json` في نفس المجلد جنب الملف التنفيذي عشان يشتغل، لأنهم مش متضمّنين جوه الـ exe (أسرار وميتنقلوش).

## الميزات الأساسية

- تسجيل دخول بيوزر نيم وباسورد (محفوظين في جدول `users` في Supabase) قبل الوصول لأي صفحة.
- عرض الراكبين الـ Active (من Google Sheet) مع تحديث تلقائي كل 5 دقايق.
- زرار لكل راكب لرفع صور (الدفعات + المحفظة من تطبيق طلبات) واستخراج بياناتها بالـ OCR.
- استخراج Complete Hours / Complete Order / Wallet بالـ OCR العادي، واستخراج Installments بنظام تعرّف ذاتي على الأرقام (بيتعلم من كل تصحيح يدوي بيعمله المستخدم).
- عمود Equation = Wallet − Installments، بلون أحمر لو موجب وأخضر لو سالب.
- أرشيف يومي: كل يوم له جدول مستقل، وتقدر تتنقل بين الأيام بمؤشر "اليوم السابق / اليوم التالي".
