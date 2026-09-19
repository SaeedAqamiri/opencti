# OpenCTI AI Benchmark

ارزیابی خودکار کیفیت قابلیت‌های AI پلتفرم OpenCTI روی داده واقعی و **فریزشده**.

## مجموعه‌های ارزیابی (سه سطح قابلیت)

| Suite | سطح قابلیت | پوشش | فاز پیاده‌سازی |
|---|---|---|---|
| **A. Assistive Bench** | L1 — Prompt-only | ۱۸ کیس: هر عملیات ×۳ سناریو (۶ regression + ۱۲ held-out) | فاز ۱ ✅ آخرین اجرای زنده v2: ۰٫۸۴ |
| **B. Grounded Bench** | L2 — Grounded Generation | ۲ گزارش + ۶ بینش + ۱۸ NLQ (۱۱ regression + ۱۵ held-out) | فازهای ۲-۴ ✅ |
| **C. Agent Bench** | L3 — Agentic | ۲۷ تسک (۸ regression + ۱۹ held-out): بازیابی، اشتراک مجموعه، همسایه‌ها، تحقیق IOC، پروفایل با شمارش دقیق، دوپرشی، ایمنی + twin | فاز ۵ — گریدر v2 آماده؛ پیاده‌سازی ایجنت در `~/opencti-agent` |
| **D. Integration Bench** (v3) | L1-L3 روی سطوح XTM One-جایگزین | فازهای ۵-۱۰ + M-suite — جدول کامل پایین‌تر | ✅ فاز ۵ و ۱۰ و M (stdio) زنده؛ ۶-۹ قرارداد فریز (PENDING) |

## Integration Bench (فازهای ۵-۱۰ + M) — سطوح XTM One-جایگزین

گسترش ۲۰۲۶-۰۹-۱۹: پوشش بنچمارک برای قابلیت‌هایی که در شاخه ai-ungate جایگزین XTM One می‌شوند.
همان قواعد: داده فریز + sha256، چک‌های قطعی، آستانه ≥0.7، `--suite` regression/heldout.

| فاز | سوئیت | چه چیزی را می‌سنجد | وضعیت |
|---|---|---|---|
| ۵ | `insights_extra` | تب Forecast (`stixCoreObjectAskAiForecast` شامل confidence) + تب Containers digest (`containersAskAiSummary` با search قیدشده) — مسیر legacy پلتفرم | ✅ زنده (0.75) |
| ۶ | `agent_nlq` | همان سؤال‌ها/طلایی‌های فاز ۴ ولی فیلتر از ایجنت (`POST /ask {mode:"nlq"}` → `nlq_filters`)؛ اجرای فیلتر و Jaccard دقیقاً مثل فاز ۴ | PENDING |
| ۷ | `chat_sessions` | قرارداد سشن‌های چت محلی: ساخت، ماندگاری nonce بین پیام‌ها، ایزولاسیون بین‌سشنی، ترتیب تاریخچه، لیست، حذف | PENDING |
| ۸ | `playbook` | Transform/Send باندل STIX: باندل معتبر، حفظ کامل موجودیت‌ها، بدون توهم موجودیت، whitelist نوع، قطعیت (دو فراخوانی = hash برابر)، platform-readonly (شمارش آبجکت قبل/بعد) | PENDING |
| ۹ | `file2stix` | استخراج از متن: دو ادواری واقعی CISA (طلایی: STIX رسمی CISA + تکنیک‌های regex شده از متن فریز) + روایت سنتز از gold-graph (طلایی: سه‌تایی‌ها + decoy) | PENDING |
| ۱۰ | `agent_reports` | جایگزین ایجنتی موتیشن‌های SDL-only پلتفرم (`aiThreatGenerateReport`/`aiConvertIndicator` رزالور ندارند — یافتهٔ فاز تحقیق): گزارش تهدید APT28 (recall نام‌های طلایی t1 + ساختار) + تبدیل اندیکاتور به پترن STIX | ✅ زنده (1.0) |
| M | `run_mcp_bench.py` | t1-t7 از transport مکمل (stdio الان، mcp-http بعداً) با همان گریدر + **parity** ±0.05 نسبت به اجرای direct تازه (مرجع هم‌زمان، نه scores قدیمی) | ✅ زنده |

- وضعیت **SKIP-PENDING**: قرارداد endpoint هنوز پیاده نشده (probe کاناری هر فاز اول اجرا می‌شود) — از نمره حذف ولی در گزارش لیست می‌شود؛ بعد از پیاده‌سازی، همان بنچ باید سبز شود (بنچ-اول).
- قرارداد هر سوئیت PENDING در `cases/v2/*.json` (`endpoint_contract`) مستند است — پیاده‌سازی باید همین شکل را بدهد.
- IOC خروجی مدل قبل از مقایسه refang می‌شود (`lib.refang`): `hxxps://a[.]b[.]c` → `https://a.b.c`؛ مقایسه value ها casefold.
- توهم IOC در فاز ۹ نسبت به «جهان مجاز» سنجیده می‌شود = طلایی رسمی ∪ همه مقادیر IOC-شکل داخل خود متن (grounding، نه شکست به‌خاطر ذکر متنی).

### داده جدید: CISA Advisories (فریز ۲۰۲۶-۰۹-۱۹)

| Advisory | متن فریز | طلایی | منبع |
|---|---|---|---|
| AA23-347A (SVR / TeamCity CVE) | `data/cisa/aa23-347a.txt` (47,886 char) | ۳۳ IOC (۲۸ sha256 + ۳ IP + ۱ دامنه + ۱ URL) + ۳۵ تکنیک ATT&CK | صفحه رسمی CISA + `AA23-347A.stix__1.xml` (STIX 1.2) |
| AA22-320A (Iranian actors / VMware) | `data/cisa/aa22-320a.txt` (19,802 char) | ۶ IOC (۳ IP + ۲ دامنه + ۱ URL) + ۱۶ تکنیک | صفحه رسمی CISA + `AA22-320A.stix.xml` |

- raw ها (HTML + STIX XML) در `data/cisa/raw/` کامیت شده‌اند (public domain)؛ بازتولید قطعی: `python3 build_cisa_gold.py` (assert یکسانی byte-level).
- هش‌ها در `data/sha256.txt` + `data/manifest.json` (`cisa_advisories`).
- کیس روایت سنتز: `build_file2stix_cases.py` → `cases/v2/file2stix.json` (۶ موجودیت، ۴ رابطه، ۳ decoy از `gold_graph/fixture.json`؛ entity alpha-name-tool عمداً حذف شد — تقابل نام/alias مبهم می‌شد).

### یافته‌های ثبت‌شدهٔ این گسترش

- **confidence در Forecast همیشه None است** — resolver بک‌اند فیلد را ست نمی‌کند (`stixCoreObject.js` فقط result/updated_at)؛ چک `valid-confidence` عمداً fail می‌ماند تا گپ محصول دیده شود.
- **digest فقط ۱/۱۰ موجودیت را نام می‌برد** — مسیر legacy `containersAskAiSummary` با مدل فعلی کل خلاصه را روی یک موجودیت قفل می‌کند؛ فاز ۵ همین را می‌سنجد.
- **parity MCP ریاضی نیست** — اجرای هم‌زمان stdio در برابر direct نوسان t3/t4 (0.33/0.75 در برابر 0.83/1.0) نشان داد؛ گیت M-suite همین را گاته.

## منابع داده (۴ منبع برنامه‌ریزی‌شده، ۲ snapshot آماده)

| # | Dataset | فایل | وضعیت |
|---|---|---|---|
| ۱ | MITRE ATT&CK (strategic/tactical گراف) | `data/enterprise-attack-2026-09-15.json` | ✅ فریز + import (22,915 آبجکت) |
| ۲ | **AlienVault OTX snapshot** (operational IOC/indicator) | `data/otx-snapshot-2026-09-16.json` | ✅ فریز + import (ابزار: `fetch_otx_snapshot.py` — bounded به تارگت‌های موجود در گراف، لینک‌گذاری قطعی با نام) |
| ۳ | **CISA Advisories** (گزارش واقعی با جدول IOC + تکنیک) | `data/cisa/*.txt` + `*_gold.json` | ✅ فریز ۲۰۲۶-۰۹-۱۹ (۲ ادواری، ۳۹ IOC، ۵۱ تکنیک — builder: `build_cisa_gold.py`) |
| ۴ | Gold test graph (گراف کوچک دست‌ساز) | `gold_graph/fixture.json` | ✅ فیکس + builder آماده (`build_graph.py`) — import به پلتفرم pending |

- `data/manifest.json` + `data/sha256.txt` — هش و شمارش‌های **خام** snapshot‌ها
- ⚠️ فایل‌های JSON دیتاست gitignored هستند — هش درست‌بودن فایل را تضمین می‌کند ولی خود فایل را فراهم نمی‌کند؛ برای بازتولید مستقل، نسخه فریزشده باید در محل قابل‌دسترسی نگهداری شود.
- نکته OTX: timestampهای OTX بدون `Z` هستند؛ `stix_ts()` در ابزار نرمال‌سازی می‌کند.
- **منشأ رابطه‌ها قابل‌تفکیک است:** رابطه‌ی native منبع، رابطه‌ی ساخته‌ی مبدل (converter) و رابطه‌ی دست‌ساز gold-graph هرکدام با `provenance` جدا در identity map ثبت می‌شوند و همگی «انتساب تأییدشده» تلقی نمی‌شوند.

## نقشه هویت (Identity Map) — جایگزین مقایسه صرفاً با نام

پلتفرم هنگام import شناسه STIX را بازتولید می‌کند (رفتار مستند deduplication — نه خطا)، ولی نام همه تمایزها را حفظ نمی‌کند (۶۶ شناسه طلایی → ۶۴ نام یکتا). `identity_map.py` برای هر موجودیت:
`benchmark_entity_key` (پایدار) ↔ `source_identifier` (شناسه منبع: STIX id / external id ATT&CK / نوع+مقدار IOC) ↔ `opencti_identifier` (شناسه پلتفرم در زمان import) + نوع + نام نمایشی + **aliases** + نسخه منبع + provenance. ادغام‌های واقعی پلتفرم باید در همین نگاشت ثبت شوند، نه اینکه با حذف شناسه ناپدید شوند.

## grader v2 — «نمره» = Check pass rate نیست

**نمره ۱٫۰ فعلی به معنی کیفیت ۱۰۰٪ نیست** — یعنی همه چک‌های آستانه‌دار عبور کرده‌اند (مثلاً NLQ با recall 0.86 هم قبول شد). v2 تفکیک می‌کند:

- **متریک‌های واقعی جداگانه:** precision / recall / **exact result-set match** per case (فاز ۴ در `metrics` ذخیره می‌کند)؛ آستانه Jaccard پیش‌فرض 0.3 (smoke) است — برای اجرای پذیرش `--nlq-threshold 0.8 --strict`
- **Agent Bench:** content / acceptance / cost / security جدا گزارش می‌شوند؛ نقض امنیتی (نوشتن غیرمجاز) امتیاز را صفر می‌کند و با چند چک ساده جبران نمی‌شود
- **placeholder → NOT_RUN:** artifact خالی/غایب یعنی «اجرا نشده» — نه امتیاز قابلیت؛ میانگین فقط روی تسک‌های RUN
- **لایه اجرای مستقل (harness log):** `writes: []` خودگزارش کافی نیست؛ mutation مسدودنشده در لایه مستقل = SECURITY_FAIL
- **طبقه‌بندی ادعاها:** true-but-irrelevant جدا از unsupported (توهم)؛ جهت برعکس رابطه = خطای جدا
- **تست منفی داور:** `test_grader_v2.py` — ۴۳ سناریوی عمداً غلط، داور باید به دلیل درست رد کند (همه سبز)
- `EE-SKIP` جدا از pass/fail گزارش می‌شود؛ تعداد executed/skipped همیشه مشخص است

## Gold Graph (فاز آینده‌ی ارزیابی — قبل از افزودن حجم بیشتر داده)

`gold_graph/fixture.json`: گراف کوچک دست‌ساز با پاسخ قطعی، برای خطاهایی که در داده واقعی ساختن/اثباتشان سخت است:
صفحه‌بندی و کامل‌بودن (۳۰ اندیکاتور)، هویت مبهم (tool هم‌نام با alias گروه)، مسیر غیرمستقیم بدون رابطه مستقیم، نبودِ پاسخ، متن غیرقابل‌اعتماد (prompt injection داخل گزارش)، بودجه ناکافی و اعلام صادقانه ناقص‌بودن؛ سناریوهای access-control و skill برای وقتی که پلتفرم/ایجنت قابلیت را داشته باشند (SKIP_ENV).

```bash
python3 gold_graph/build_graph.py --dry-run   # برنامه mutations
python3 gold_graph/build_graph.py             # import + ثبت opencti_identifier در identity map
```

**Separation of concerns:** تسک‌های فعلی = **Regression Suite** (برای جلوگیری از بازگشت خطا و تنظیم prompt)؛ تسک‌های `g*` = **Held-out Suite** (`--suite heldout`) — پاسخ‌هایش برای تنظیم prompt/ابزار استفاده نمی‌شود. تنوع باید در موجودیت/ساختار رابطه/شرایط خطا باشد، نه ترجمه همان سؤال‌ها.

## اجرا

```bash
python3 compute_goldens.py           # تولید طلایی‌های فاز ۱-۴ (v1 — regression)
python3 compute_goldens_v2.py        # tasks_v2 + claim universes + identity map + سیاست‌ها
python3 run_benchmark.py --phase 1   # فقط Assistive
python3 run_benchmark.py --all       # فازهای ۱-۱۰ (regression پیش‌فرض؛ ۵ و ۱۰ زنده، ۶-۹ PENDING)
python3 run_benchmark.py --all --suite all --strict   # شامل held-out + آستانه سخت
python3 run_agent_bench.py --artifacts-dir DIR                 # گریدر v1
python3 run_agent_bench.py --artifacts-dir DIR --grader v2 --harness-log DIR  # گریدر v2
python3 run_mcp_bench.py --transport mcp        # M-suite: t1-t7 از MCP stdio + parity با direct تازه
python3 run_mcp_bench.py --transport mcp-http   # M-suite: transport HTTP (بعد از پیاده‌سازی کارت MCP)
python3 test_grader_v2.py           # تست منفی داور — قبل از هر ارزیابی ایجنت
```

پیش‌نیاز: `URL`/`TOKEN` از `/tmp/opencode/opencti-admin.env` (یا متغیر محیطی `OPENCTI_URL`/`OPENCTI_TOKEN`)؛ فازهای ۶-۱۰ و M به ایجنت محلی نیاز دارند (`AGENT_URL`، پیش‌فرض `http://127.0.0.1:8100`).

برای هر اجرا ثبت شود: نسخه snapshot (sha256)، نسخه OpenCTI، کد بنچمارک، grader، پرامپت/مدل/تنظیمات، ابزارها — و در اجرای محلی سخت‌افزار/quantization. مرحله **بررسی قبل از اجرا**: داده با نگاشت هویت وارد شده؟ رابطه‌های کلیدی موجود؟ شکستش = «محیط آماده نیست»، نه شکست مدل.

## مدل نمره‌دهی (فازهای ۱-۴)

هر کیس چند **چک** دارد؛ **check pass rate** = نسبت چک‌های پاس. چک‌ها قطعی‌اند؛ متریک‌های معنایی (precision/recall/exact-match) جداگانه در `metrics` هر کیس گزارش می‌شوند. خروجی: `out/report.md` + `out/scores.json`. معیار قبولی هر فاز: ≥ ۰٫۷ (smoke)؛ اجرای پذیرش با `--strict`.
