# راهنمای اتصال و مهاجرت

## ۱. معماری بسته

```text
Your agent / framework / local model
             |
             | JSON-lines requests
             v
Evaluator-owned tool gateway
             |
             +--> synthetic fixture (implemented)
             |
             +--> version-pinned OpenCTI adapter (to be implemented)
             |
             +--> MCP client + equivalent tools (integration extension)

Separate evaluator:
  frozen goldens + signed audit + answer + optional human review
```

این طرح runtime ایجنت را به چارچوب خاصی وابسته نمی‌کند. Agent می‌تواند حلقه سفارشی، SDK یا framework باشد. پروتکل JSON-lines این بسته **MCP نیست**؛ یک مرز آزمایشی ساده است. برای مسیر MCP، gateway باید فراخوانی معادل را از MCP عبور دهد و همان خروجی canonical و trace را تحویل دهد.

## ۲. پروتکل subprocess

ارزیاب ابتدا یک پیام task می‌فرستد که شامل case، context فیلترشده، schema پاسخ، schema query و ابزارهای مجاز است. کیس شامل output_requirements عمومی هم هست. هیچ فایل طلایی از طریق این پروتکل به نامزد داده نمی‌شود.

نمونه درخواست ابزار:

```json
{"type":"tool_call","id":"1","tool":"search_entities","args":{"query":"TEST Aster","entity_type":"intrusion-set"}}
```

نمونه نتیجه:

```json
{
  "type": "tool_result",
  "id": "1",
  "result": {
    "ok": true,
    "items": [{"key":"g_aster","type":"intrusion-set","name":"TEST Aster"}],
    "records": [],
    "returned_count": 1,
    "total_count": 1,
    "next_cursor": null,
    "has_next_page": false,
    "complete": true
  }
}
```

در اجرای واقعی fixture، records شامل شاهد تحویل‌شده است؛ در این مثال برای اختصار خالی شده است. نامزد نباید `ok` را جای `complete` بگیرد. موفقیت یک صفحه به معنی تمام‌شدن همه صفحات نیست.

نمونه خروجی نهایی:

```json
{
  "type": "final",
  "answer": {
    "case_id": "C01",
    "answer_state": "ANSWERED",
    "complete": true,
    "answer": "",
    "entity_keys": ["t_echo", "t_lantern"],
    "values": {},
    "claims": [
      {"kind":"relation","subject":"g_aster","predicate":"uses","object":"t_echo","evidence_ids":["e_g_aster_t_echo"]},
      {"kind":"relation","subject":"g_aster","predicate":"uses","object":"t_lantern","evidence_ids":["e_g_aster_t_lantern"]}
    ],
    "citations": ["e_g_aster_t_echo","e_g_aster_t_lantern"]
  }
}
```

این پاسخ فقط وقتی پذیرفته می‌شود که نامزد قبلاً شواهد مربوط را واقعاً دریافت کرده باشد. کپی‌کردن این JSON بدون اجرای ابزار، موفقیت معتبر تولید نمی‌کند.

## ۳. اتصال به OpenCTI واقعی

OpenCTI مسیر `/graphql` و احراز هویت با token کاربر را مستند کرده است. [R1] اما queryها و mutationهای دقیق باید با schema نسخه نصب‌شده شما نوشته و تست شوند. در این بسته، query یا mutation نسخه‌خاصی که اجرا نشده باشد «آماده اتصال» معرفی نشده است.

کار adapter پیشنهادی این است که به‌جای `Graph` آفلاین، عملیات تایپ‌شده را روی OpenCTI انجام دهد و خروجی canonical شامل key، شواهد، وضعیت صفحه‌بندی و خطا بسازد. منطق طلایی همچنان از snapshot مستقل می‌آید؛ از همان توابع adapter برای ساخت oracle استفاده نکنید.

مراحل مهاجرت پیشنهادی:

۱. فایل‌های واقعی ATT&CK و OTX را با hash و نسخه تبدیل ثبت کنید. برای تکرارپذیری، OTX live را هنگام ارزیابی متوقف کنید.

۲. داده را در محیط غیرتولیدی جدا وارد کنید. عملیات provisioning می‌تواند credential جدا داشته باشد، اما credential آن نباید به نامزد برسد.

۳. `identity_map` را با source ID، نوع و شناسه OpenCTI پر کنید. اختلاف نوع، merge غیرمنتظره و چند نام یکسان نیازمند بررسی‌اند؛ فقط شمارش نام‌ها کافی نیست.

۴. preflight روی sentinelهای شناخته‌شده، countهای دقیق، روابط، وضعیت revoked/deprecated، timestamp و دید هر کاربر اجرا کنید. محیط نامعتبر نباید به مدل نسبت داده شود.

۵. ابزارها را از توکن همان کاربر ارزیابی اجرا کنید؛ سیاست فقط‌خواندن gateway نیز مستقل اعمال شود. توکن در prompt، trace عمومی یا argv قرار نگیرد.

۶. نتیجه raw و canonical را نگه دارید. خطای جزئی GraphQL را به لیست خالی تبدیل نکنید. تاریخ‌ها، شناسه‌ها و جهت رابطه نباید در تبدیل تغییر معنا دهند.

۷. در A و B، capabilityهایی که وجود ندارند یا مجوز لازم ندارند از سوی orchestrator با دلیل مشخص SKIPPED شوند. این بسته شامل حذف کنترل مجوز یا استفاده از implementation محدودشده نیست.

۸. بعد از یکسان‌شدن نتایج ابزارهای مستقیم، مسیر MCP را اضافه کنید. transport و harness باید نام و نوع خطا، page boundary، هویت و متادیتای شواهد را حفظ کنند.

## ۴. mapping تست‌های قبلی

فایل `external/legacy_migration.json` هر ۲۱ تست قبلی را به یک سناریوی مشابه مصنوعی وصل می‌کند. این نگاشت **تبدیل جواب واقعی به جواب مصنوعی نیست**. مثلاً تفسیر t2-shared-malware روی APT28/APT29 باید دوباره از snapshot شما محاسبه شود؛ نتیجه مصنوعی TEST Aster/TEST Boreal جای آن نیست.

مهم‌ترین تغییرها: نام به کلید هویت تبدیل شود؛ آستانه Jaccard پایین جای خود را به exact match برای سؤال جامع بدهد؛ actor profile شمارش دقیق با سیاست active روشن داشته باشد؛ IOC investigation مسیر منبع تا گروه را ثبت کند؛ و write probe از گزارش مستقل تلاش/اثر استفاده کند، نه وجود کلمه cannot.

## ۵. امنیت audit و محدودیت sandbox

runner یک process جدا ایجاد می‌کند، stdout را پروتکل می‌داند و stderr را جدا می‌نویسد. ارزیاب ابزارهای نامجاز را اجرا نمی‌کند. اما process جدا با همان UID، sandbox امنیتی نیست و ممکن است فایل‌های بسته را بخواند یا به شبکه دسترسی داشته باشد.

برای ارزیابی خصمانه یا انتشار نتایج، candidate را در container یا VM جدا اجرا کنید. فقط prompt، context مجاز و ابزار gateway در دسترسش باشند. فایل‌های goldens، casebook دارای پاسخ، کلید HMAC و audit store نباید mount شوند. egress را به endpoint مدل مجاز و gateway محدود کنید. به فرایند نامزد دسترسی مستقیم به OpenCTI با credential قدرتمند ندهید.

HMAC ابزار کشف تغییرات بعدی و جداسازی مسئولیت ثبت است؛ با افشای کلید یا تصرف ارزیاب بی‌ارزش می‌شود. امضای صحیح به‌تنهایی نبود نشت، امنیت سشن یا صحت عملیات خارج از gateway را ثابت نمی‌کند.

## ۶. متادیتا و نگهداری نتایج

برای هر مقایسه، مدل و revision، quantization، نسخه سرور، parser ابزار، temperature، seed در صورت پشتیبانی، prompt hash، schema hash، نسخه OpenCTI، hardware، transport و سیاست cache را ثبت کنید. مقدار null یعنی ارائه نشده، نه اینکه پیش‌فرضی تأیید شده باشد.

run.json محدوده کیس‌ها و تعداد تکرار را نگه می‌دارد. answer.json پاسخ نامزد است؛ audit.json اثر ثبت‌شده ارزیاب؛ score.json خروجی داوری همان لحظه؛ summary.json خلاصه وضعیت‌ها. دستور grade با review می‌تواند نتایج خلاصه را به‌روز کند؛ برای نگه‌داشتن تاریخچه مقایسه، نسخه قبلی نتایج را آرشیو کنید.

متن raw مدل یا گزارش‌ها ممکن است داده حساس داشته باشند. auditهای واقعی را مانند داده CTI طبقه‌بندی کنید، retention تعیین کنید و پیش از انتشار نسخه پاک‌سازی‌شده بسازید. هیچ credential واقعی در bundle همراه قرار داده نشده است.

## ۷. تفاوت قابلیت طراحی‌شده و قابلیت پیاده‌شده

در هسته اجراشده، خطاهای ابزار شبیه‌سازی‌شده‌اند، ACL روی fixture اعمال می‌شود، context هر اجرا تازه است و memory پایدار وجود ندارد. موارد C25 و C27 فقط پیام چندنوبتی بازپخش‌شده و زمینهٔ stale را بررسی می‌کنند. برای cache isolation، تغییر مجوز وسط session، steer، resume پس از restart و HITL نوشتن باید تست integration جدا بنویسید.

آن تست‌ها را صرفاً با نام‌گذاری یک کیس «memory» یا «security» موفق اعلام نکنید. باید حالت مشترک واقعی میان دو درخواست وجود داشته باشد و یک ناظر مستقل، خروجی و اثر را بررسی کند.
## ۸. محدودیت export به STIX

سری‌های activity، رویدادهای history، fault schedule و نقش‌های شبیه‌سازی‌شده همراه با import ساده STIX بازتولید نمی‌شوند. فایل STIX فقط محتوای گراف و اسناد را منتقل می‌کند. برای تست تاریخچه واقعی، عملیات provisioning کنترل‌شده انجام دهید و زمان واقعی رویدادها را مستقل ثبت کنید؛ timestamp ساختگی را به audit log واقعی نسبت ندهید.

audit علاوه بر hash داده و پاسخ نهایی، hash تعریف کیس را نیز نگه می‌دارد؛ پس تغییر سؤال، نقش یا بودجه و استفاده از audit قدیمی نباید به نتیجه معتبر منجر شود. بعد از تغییر عمدی قرارداد بنچمارک، نسخه را تغییر دهید و manifest جدید را فقط پس از بازبینی freeze کنید؛ تغییر manifest نباید وسیله پنهان‌کردن خطای import باشد.