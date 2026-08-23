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

## 6. تشغيل السيستم

```powershell
python app.py
```

افتح المتصفح على: http://127.0.0.1:5000 (بيوديك تلقائي لـ `/riders`).

## 7. النشر على Render (عشان يشتغل على الموبايل واللاب من أي مكان)

Vercel مش مناسب للسيستم ده لأنه مش بيدعم تشغيل Tesseract. هننشر على **Render** باستخدام Docker (الملف `Dockerfile` جاهز في المشروع).

### الخطوات

1. **ثبّت Git** لو مش متثبت: https://git-scm.com/downloads
2. اعمل حساب على [GitHub](https://github.com) لو مالكش، واعمل repository جديد (private).
3. من مجلد المشروع:
   ```powershell
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin <رابط الـ repo بتاعك>
   git push -u origin main
   ```
   (ملفات `.env` و `service_account.json` متسجلاش لأنهم في `.gitignore` — كويس، دول أسرار)
4. اعمل حساب على [Render](https://render.com) وسجّل دخول بـ GitHub.
5. من الداشبورد: **New > Web Service** واختار الـ repo بتاعك.
6. Render هياكتشف الـ `Dockerfile` أوتوماتيك (اختار Environment: **Docker**).
7. في **Environment Variables** ضيف:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = **افتح ملف `service_account.json` والصق محتواه كامل كسطر واحد**
   - `GOOGLE_SHEET_ID`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `FLASK_SECRET_KEY` (أي نص عشوائي طويل)
   - `SHEETS_CACHE_TTL_SECONDS` = `60` (اختياري)
8. دوس **Create Web Service** — Render هيبني ويشغّل السيستم، وهيديك رابط زي `https://your-app.onrender.com` يشتغل من أي جهاز (موبايل أو لابتوب) من غير أي إعدادات شبكة زيادة.

### ملاحظة مهمة

مجلد `uploads/` (صور الرفع) بيتصفّر مع كل عملية نشر (deploy) جديدة على الخطة المجانية في Render، لأن التخزين مؤقت مش دائم. أما الأرقام اللي اتعلمها النظام (digit templates) فمحفوظة بشكل دائم في جدول `digit_templates` بـ Supabase، فمش بتضيع مع أي deploy جديد.

## الميزات الأساسية

- تسجيل دخول بيوزر نيم وباسورد (محفوظين في جدول `users` في Supabase) قبل الوصول لأي صفحة.
- عرض الراكبين الـ Active (من Google Sheet) مع تحديث تلقائي كل 5 دقايق.
- زرار لكل راكب لرفع صور (الدفعات + المحفظة من تطبيق طلبات) واستخراج بياناتها بالـ OCR.
- استخراج Complete Hours / Complete Order / Wallet بالـ OCR العادي، واستخراج Installments بنظام تعرّف ذاتي على الأرقام (بيتعلم من كل تصحيح يدوي بيعمله المستخدم).
- عمود Equation = Wallet − Installments، بلون أحمر لو موجب وأخضر لو سالب.
- أرشيف يومي: كل يوم له جدول مستقل، وتقدر تتنقل بين الأيام بمؤشر "اليوم السابق / اليوم التالي".
