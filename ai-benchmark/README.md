# OpenCTI AI Benchmark

ارزیابی خودکار کیفیت قابلیت‌های AI پلتفرم OpenCTI روی داده واقعی و **فریزشده**.

## مجموعه‌های ارزیابی (سه سطح قابلیت)

| Suite | سطح قابلیت | پوشش | فاز پیاده‌سازی |
|---|---|---|---|
| **A. Assistive Bench** | L1 — Prompt-only | fixSpelling / makeShorter / makeLonger / changeTone / summarize / explain | فاز ۱ ✅ (نمره ۱.۰) |
| **B. Grounded Bench** | L2 — Grounded Generation | container report / AI insights (activity, history, digest) / NLQ | فازهای ۲-۴ |
| **C. Agent Bench** | L3 — Agentic | MCP search / graph traversal / investigation / write-action / permissions | فاز ۵ |

## داده فریزشده (چهار دیتاست پروژه)

| # | Dataset | فایل | وضعیت |
|---|---|---|---|
| ۱ | MITRE ATT&CK (strategic/tactical گراف) | `data/enterprise-attack-2026-09-15.json` | ✅ import شد (22,915 آبجکت) |
| ۲ | **AlienVault OTX snapshot** (operational IOC/indicator) | `data/otx-snapshot-2026-09-16.json` | ✅ فریز + import (ابزار: `fetch_otx_snapshot.py` — bounded به تارگت‌های موجود در گراف، لینک‌گذاری قطعی با نام، بدون heuristic) |
| ۳ | Threat reports / PDFs (ورودی ساخت‌نیافته) | — | ⏳ |
| ۴ | Gold test graph (پاسخ قطعی) | — | ⏳ |

- `data/manifest.json` + `data/sha256.txt` — هش و شمارش‌های **خام** snapshot‌ها (شامل موارد deprecated/revoked)
- فایل‌های JSON دیتاست gitignored هستند (فقط manifest/hash کامیت می‌شود)
- برای تکرارپذیری، هارنس فقط از همین فایل‌های فریز golden می‌سازد.
- نکته OTX: timestampهای OTX بدون `Z` هستند؛ `stix_ts()` در ابزار نرمال‌سازی می‌کند (باگ قبلی: رد شدن همه indicatorها با MISSING_REFERENCE).

## corpora برنامه‌ریزی‌شده (افزودنی‌های آینده)

- **IOC snapshot**: مجموعه کنترل‌شده از observable ها (IP/domain/hash) — جایگزین OTX برای پوشش ضعف IOC دیتاست ATT&CK — برای تست report/insights با جدول IOC
- **Threat reports**: ۱۰-۲۰ گزارش عمومی (PDF/متن خام) برای سناریوهای خلاصه‌سازی فایل
- **Gold Graph**: گراف کوچک دست‌ساز با پاسخ‌های قطعی برای سناریوهای multi-hop (مثلاً «بدافزارهای مرتبط با آسیب‌پذیری‌های CVSS>9»)

## طراحی Agent Bench (فاز ۵) — metrics

| Metric | تعریف |
|---|---|
| Task success | انجام کامل وظیفه طبق معیار طلایی |
| Graph accuracy | صحت موجودیت‌ها/رابطه‌های خوانده‌شده یا ساخته‌شده |
| Tool-call validity | نسبت فراخوانی‌های ابزار با آرگومان‌های معتبر |
| Hallucinated relations | رابطه‌های ادعایی بدون پشتوانه در گراف |
| Unauthorized actions | اقدامات خارج از مجوز کاربر (باید صفر باشد) |
| Tool-call count / Latency | هزینه انجام هر وظیفه |

## اجرا

```bash
python3 compute_goldens.py          # تولید طلایی‌ها از data/ فریزشده
python3 run_benchmark.py --phase 1  # فقط Assistive
python3 run_benchmark.py --all      # همه (فازهای گیت‌شده SKIP-EE می‌گیرند)
```

پیش‌نیاز: `URL`/`TOKEN` از `/tmp/opencode/opencti-admin.env` (یا متغیر محیطی `OPENCTI_URL`/`OPENCTI_TOKEN`).

## مدل نمره‌دهی

هر کیس چند **چک** دارد؛ امتیاز کیس = نسبت چک‌های پاس. چک‌ها قطعی‌اند (نسبت طول،
حفظ کلیدواژه، recall موجودیت‌ها، Jaccard نتایج NLQ با طلایی، اعتبار trend و…).
خروجی: `out/report.md` + `out/scores.json`. معیار قبولی هر فاز: امتیاز ≥ ۰٫۷.
