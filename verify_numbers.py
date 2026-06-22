# -*- coding: utf-8 -*-
"""
verify_numbers — number-grounding верификатор текстов LLM-агентов.

Правило продукта: ДЕНЬГИ в тексте агента обязаны существовать в контракте
(analysis.json). Проценты и счётчики (КП/недели/акты) — сверяются с предупреждением.
Даты, годы, номера стандартов/законов — маскируются (не числа-факты).

Выход: вердикт по каждому числу → verified / WARN / CRITICAL.
CRITICAL > 0 → exit code 1 (текст бракуется, публиковать нельзя).
"""
import json
import re
import sys

ANALYSIS = r"C:\Users\User\Claude\Projects\ai-findir-lab\analysis.json"

MASKS = [
    r"\d{4}-\d{2}-\d{2}",            # ISO-даты
    r"\d{2}\.\d{2}\.\d{4}",          # 08.06.2026
    r"\d{2}\.\d{2}-\d{2}\.\d{2}",    # 01.04-03.04
    r"(?:ISO|ИСО)\s*\d+(?::\d{4})?",  # ISO 9001:2026
    r"ГОСТ\s*(?:Р|РВ)?\s*[\d.]+(?:-\d{4})?",
    r"ТР\s*ТС\s*\d+/\d+",
    r"\d+-ФЗ",
    r"\b(?:19|20)\d{2}\b",           # одиночные годы
    r"\d{1,2}:\d{2}",                # время
]


def collect_contract_numbers(A):
    big, ratios, small = set(), set(), set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, bool):
            return
        elif isinstance(v, (int, float)):
            a = abs(v)
            if a >= 1000:
                big.add(round(v))
            elif 0 < a < 20:
                ratios.add(float(v))
                if float(v).is_integer():
                    small.add(int(round(v)))
            if 20 <= a < 1000 and float(v).is_integer():
                small.add(int(round(v)))
        elif isinstance(v, str):
            # числа внутри строк контракта (тексты алертов/действий) тоже валидны
            for mtxt in re.findall(r"\d[\d\s ]{3,}\d", v):
                try:
                    big.add(round(float(re.sub(r"[\s ]", "", mtxt))))
                except ValueError:
                    pass
            for mtxt in re.findall(r"~?(\d{1,3})\s*(?:КП|нед|акт)", v):
                small.add(int(mtxt))

    walk(A)
    return big, ratios, small


def verify_text(text, A, label="text"):
    big, ratios, small = collect_contract_numbers(A)
    masked = text
    for mk in MASKS:
        masked = re.sub(mk, " §masked§ ", masked)

    findings = []

    def add(kind, raw, value, ok, sev):
        findings.append({"kind": kind, "raw": raw.strip(), "value": value,
                         "ok": ok, "severity": "ok" if ok else sev})

    # 1) деньги с разделителями: 2 681 535
    for m in re.finditer(r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?", masked):
        v = float(re.sub(r"[  ]", "", m.group(0)).replace(",", "."))
        ok = round(v) in big or any(abs(b - v) <= 1 for b in big)
        add("money", m.group(0), v, ok, "CRITICAL")
    masked = re.sub(r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?", " §m§ ", masked)

    # 2) компактные: 2,68 млн / 220 тыс / 1.5М
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(млн|тыс|М\b|K\b|к\b)", masked):
        num = float(m.group(1).replace(",", "."))
        mult = 1e6 if m.group(2).lower().startswith(("млн", "м")) else 1e3
        v = num * mult
        prec = len(m.group(1).split(",")[-1].split(".")[-1]) if ("," in m.group(1) or "." in m.group(1)) else 0
        ok = any(abs(b - v) <= 0.5 * mult / (10 ** prec) for b in big)
        add("money~", m.group(0), v, ok, "CRITICAL")
    masked = re.sub(r"(\d+(?:[.,]\d+)?)\s*(млн|тыс|М\b|K\b|к\b)", " §c§ ", masked)

    # 3) проценты: 45% / 9.3%
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", masked):
        p = float(m.group(1).replace(",", "."))
        prec = 1 if ("," in m.group(1) or "." in m.group(1)) else 0
        ok = any(abs(r * 100 - p) <= 0.5 / (10 ** prec) + 1e-9 for r in ratios)
        add("percent", m.group(0), p, ok, "WARN")
    masked = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", " §p§ ", masked)

    # 4) голые большие: 500000
    for m in re.finditer(r"\b\d{4,}\b", masked):
        v = float(m.group(0))
        ok = round(v) in big
        add("money", m.group(0), v, ok, "CRITICAL")
    masked = re.sub(r"\b\d{4,}\b", " §b§ ", masked)

    # 5) счётчики в контексте: ~37 КП, 16, 6 нед, 82 акта
    for m in re.finditer(r"[~≈]?\s*(\d{1,3})(?=\s*(?:КП|кп|нед|акт|звонк|встреч|сделк|обещан))", masked):
        v = int(m.group(1))
        ok = v in small
        add("count", m.group(0), v, ok, "WARN")

    crit = [f for f in findings if f["severity"] == "CRITICAL"]
    warn = [f for f in findings if f["severity"] == "WARN"]
    return {"label": label, "total": len(findings),
            "verified": sum(1 for f in findings if f["ok"]),
            "critical": crit, "warnings": warn,
            "pass": not crit}


def main(paths):
    A = json.load(open(ANALYSIS, encoding="utf-8"))
    overall_ok = True
    for p in paths:
        try:
            text = open(p, encoding="utf-8").read()
        except UnicodeDecodeError:
            text = open(p, encoding="cp1251", errors="replace").read()
        res = verify_text(text, A, label=p.split("\\")[-1])
        status = "PASS" if res["pass"] else "FAIL"
        print(f"[{status}] {res['label']}: чисел {res['total']}, подтверждено {res['verified']}, "
              f"CRITICAL {len(res['critical'])}, WARN {len(res['warnings'])}")
        for f in res["critical"]:
            print(f"   !! не из контракта: «{f['raw']}» ({f['value']:.0f})")
        for f in res["warnings"][:6]:
            print(f"   ?  не сверилось: «{f['raw']}»")
        overall_ok &= res["pass"]
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    args = sys.argv[1:] or [r"C:\Users\User\Claude\Projects\ai-findir-lab\BRIEF.txt"]
    main(args)
