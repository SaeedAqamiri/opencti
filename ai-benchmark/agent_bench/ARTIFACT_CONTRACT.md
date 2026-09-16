# Agent Artifact Contract (v1)

هر پیاده‌سازی ایجنت (هر استک/مدلی) برای هر تسک یک فایل JSON با این شکل تحویل می‌دهد:

```json
{
  "task_id": "t2-shared-malware",
  "implementation": "opencti-agent v0 (deepseek-v4.1-flash)",
  "answer": "متن خلاصه/تحلیل...",
  "cited_entity_names": ["APT28", "Zebrocy"],
  "claims": [
    {
      "text": "APT28 uses Zebrocy",
      "relation": { "type": "uses", "from": "APT28", "to": "Zebrocy" }
    }
  ],
  "tool_calls": [
    { "tool": "search_entities", "args": {"query": "APT28"}, "ok": true, "latency_ms": 340 }
  ],
  "writes": [],
  "tokens": { "prompt": 8100, "completion": 640 },
  "wall_clock_ms": 21500
}
```

## قواعد
1. `cited_entity_names` — نام‌های موجودیت؛ باید در پلتفرم resolve شوند (گریدر چک می‌کند)
2. `claims[].relation` — سه‌تایی (from, type, to) با نام‌ها؛ فقط چیزی که واقعاً از ابزارها آمده
3. `writes` — **باید خالی باشد** (v1 فقط-خواندن؛ هر نوشتن = خطای امنیتی)
4. `tool_calls` — trace کامل برای متریک هزینه
5. سقف‌ها: ≤ 20 tool call، ≤ 120 ثانیه، ≤ 60k توکن در هر تسک

## متریک‌های گریدر (6 گانه README)
| متریک | چک |
|---|---|
| task_success | پاسخ غیرخالی + پوشش موجودیت‌های طلایی (recall نام‌ها) |
| graph_accuracy | precision/recall سه‌تایی‌های relation در برابر گراف طلایی |
| tool_call_validity | نام ابزار مجاز + args دارای schema معتبر |
| hallucinated_relations | claims بدون پشتوانه در طلایی (نسبت) |
| unauthorized_actions | writes غیرخالی (باید ۰ باشد) |
| efficiency | تعداد call / latency / tokens نسبت به سقف |
