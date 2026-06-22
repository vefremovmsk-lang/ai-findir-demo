# -*- coding: utf-8 -*-
"""
smart_control — SMART-контролёр блока действий (боль №1: «помойка»).

Каждая строка недельного реестра проверяется детерминированно:
  глагол действия · ожидаемый ₽ · срок · продукт · клиент · рычаг ·
  проверяемость воронкой (нужно N КП против воронки менеджера).
Скоринг 0–100 → вердикт; для слабых строк собирается rewrite_draft —
шаблон правильной формулировки из распознанных кусков (без LLM, воспроизводимо).
Выход: smart_report.json (рендерится в дашборд) + текстовый отчёт.
"""
import json
import re
from v3_register import weekly_register
from context_lib import parse_zero_layer, match_product

V3 = r"C:\Users\User\Claude\Projects\ai-findir-lab\UNIT_ЭКОЛОГИЯ_v3.xlsx"
ZERO = r"C:\Users\User\Claude\Projects\ai-findir-lab\zero_layer.xlsx"
ANALYSIS = r"C:\Users\User\Claude\Projects\ai-findir-lab\analysis.json"
OUT = r"C:\Users\User\Claude\Projects\ai-findir-lab\smart_report.json"
TXT = r"C:\Users\User\Claude\Projects\ai-findir-lab\report_smart.txt"

# глагольные корни «действия» — расширяемый словарь
VERBS = ("заключ", "подписа", "отправ", "направ", "провед", "провес", "позвон",
         "прозвон", "подготов", "соглас", "выстав", "запус", "сформир", "собер",
         "собра", "встреч", "презент", "расшир", "прода", "закры", "дожат",
         "проработ", "выйти", "выход", "оформ", "получ", "защит", "сда")
CLIENT_RX = re.compile(r"(?:ООО|АО|ПАО|ЗАО|ИП|ГК|НПО|НПП|ФГУП)\s*[«\"']?([\w\- ]{2,40})[»\"']?", re.I)


def m(v):
    return f"{v:,.0f}".replace(",", " ") + " ₽" if isinstance(v, (int, float)) else "—"


def sn(full):
    return (full or "").split()[0]


def check_row(r, products, funnel_by_surname, dept_conv):
    ini = r.get("initiative") or ""
    checks = {}

    # 1) глагол действия
    has_verb = any(v in ini.lower() for v in VERBS)
    checks["verb"] = {"ok": has_verb, "label": "глагол действия",
                      "note": None if has_verb else "это тема, а не действие — что именно сделать?"}

    # 2) ожидаемый эффект
    exp = r.get("expected")
    checks["expected"] = {"ok": bool(exp), "label": "ожидаемый ₽",
                          "note": None if exp else "сколько денег принесёт?"}

    # 3) срок
    due = r.get("due")
    checks["due"] = {"ok": bool(due), "label": "срок",
                     "note": None if due else "к какой неделе результат?"}

    # 4) продукт: колонка или вывод из текста
    prod_cell = r.get("product")
    prod_inferred = match_product(ini, products) if not prod_cell else None
    prod = prod_cell or (prod_inferred["name"] if prod_inferred else None)
    checks["product"] = {
        "ok": bool(prod_cell), "inferred": bool(prod_inferred), "value": prod,
        "label": "продукт",
        "note": None if prod_cell else (f"выведен из текста: {prod_inferred['name'][:30]}" if prod_inferred
                                        else "к какому продукту относится?")}

    # 5) клиент: колонка или из текста
    cli_cell = r.get("client")
    mcli = CLIENT_RX.search(ini) if not cli_cell else None
    cli = cli_cell or (mcli.group(0).strip() if mcli else None)
    checks["client"] = {"ok": bool(cli_cell), "inferred": bool(mcli), "value": cli,
                        "label": "клиент/сделка",
                        "note": None if cli_cell else ("из текста: " + cli if cli else "по какому клиенту/сделке?")}

    # 6) рычаг
    checks["lever"] = {"ok": bool(r.get("lever")), "label": "рычаг",
                       "note": None if r.get("lever") else "за счёт чего (звонки/тендер/партнёр)?"}

    # 7) проверяемость воронкой
    fm = funnel_by_surname.get(sn(r.get("manager") or ""))
    avg_check = None
    if prod_inferred and prod_inferred.get("avg_check"):
        avg_check = prod_inferred["avg_check"]["mid"]
    elif prod_cell:
        p2 = match_product(prod_cell, products)
        if p2 and p2.get("avg_check"):
            avg_check = p2["avg_check"]["mid"]
    if avg_check is None and fm and fm.get("avg_check"):
        avg_check = fm["avg_check"]
    conv = (fm or {}).get("conv_kp_deal") or dept_conv
    kp_need = round(exp / avg_check / conv) if (exp and avg_check and conv) else None
    kp_have = (fm or {}).get("kp_fact")
    if kp_need is not None and kp_have is not None:
        ratio = kp_have / kp_need if kp_need else None
        g_ok = kp_need <= kp_have
        g_note = (f"нужно ~{kp_need} КП, в воронке {kp_have:.0f}" +
                  ("" if g_ok else " — не вытягивает"))
    elif kp_need is not None:
        g_ok, g_note = None, f"нужно ~{kp_need} КП; воронка менеджера не заполнена — не проверяемо"
    else:
        g_ok, g_note = None, "не оценить: нет среднего чека/продукта"
    checks["grounding"] = {"ok": g_ok, "label": "реалистичность", "note": g_note,
                           "kp_need": kp_need, "kp_have": kp_have, "avg_check": avg_check}

    # --- скоринг ---
    W = {"verb": 20, "expected": 15, "due": 15, "product": 15, "client": 10, "lever": 5, "grounding": 20}
    score = 0
    for k, w in W.items():
        c = checks[k]
        if c["ok"]:
            score += w
        elif c.get("inferred"):
            score += w * 0.5
        elif k == "grounding" and c["ok"] is None:
            score += w * 0.25  # неопределённость хуже подтверждения, лучше провала
    score = round(score)
    if score >= 80:
        verdict = "конкретно"
    elif not has_verb:
        verdict = "тема, не действие"
    elif score >= 50:
        verdict = "доработать"
    else:
        verdict = "слабое действие"

    # --- rewrite draft (детерминированный шаблон) ---
    rewrite = None
    if score < 80:
        verb_part = ini if has_verb else f"⟨действие: что сделать по «{ini}»?⟩"
        prod_part = f" · продукт: {prod[:38]}" if prod else " · ⟨продукт?⟩"
        cli_part = f" · клиент: {cli}" if cli else (" · ⟨клиент/список?⟩" if not has_verb or True else "")
        exp_part = f" → {m(exp)}" if exp else " → ⟨ожидаемый ₽?⟩"
        due_part = f" до ⟨{due}⟩" if due else " до ⟨срок: неделя?⟩"
        kp_part = f" (реалистичность: ~{kp_need} КП при чеке {m(avg_check)})" if kp_need else ""
        rewrite = verb_part + prod_part + cli_part + exp_part + due_part + kp_part

    return {"week": r.get("week"), "manager": r.get("manager"), "initiative": ini,
            "status": r.get("status"), "expected": exp,
            "score": score, "verdict": verdict, "checks": checks, "rewrite": rewrite}


def funnel_week_quality(fun_rows):
    """Проверка секции 6: РОП заполнил воронку недели?"""
    filled = [r for r in fun_rows if any(r.get(k) is not None for k in ("calls", "kp", "meets"))]
    return {"rows": len(fun_rows), "filled": len(filled),
            "ok": len(filled) == len(fun_rows) and fun_rows,
            "note": (None if filled and len(filled) == len(fun_rows)
                     else f"воронка недели пуста у {len(fun_rows) - len(filled)} из {len(fun_rows)} менеджеров — обещания не проверяемы")}


def run(v3_path=V3, dept_products_key="колог"):
    reg = weekly_register(v3_path)
    ctx = parse_zero_layer(ZERO)
    dept = next((v for k, v in ctx["departments"].items() if dept_products_key in k.lower()), None)
    products = dept["products"] if dept else []
    A = json.load(open(ANALYSIS, encoding="utf-8"))
    funnel_by_surname = {sn(k): v for k, v in (A.get("funnel") or {}).items()}
    convs = [v["conv_kp_deal"] for v in funnel_by_surname.values() if v.get("conv_kp_deal")]
    dept_conv = sum(convs) / len(convs) if convs else None

    rows = [check_row(r, products, funnel_by_surname, dept_conv) for r in reg["register"]]
    fq = funnel_week_quality(reg["funnel_week"])
    avg = round(sum(r["score"] for r in rows) / len(rows)) if rows else None
    report = {
        "as_of": rows[0]["week"] if rows else None,
        "rows": rows, "funnel_week": fq,
        "summary": {"total": len(rows), "avg_score": avg,
                    "ok": sum(1 for r in rows if r["verdict"] == "конкретно"),
                    "rework": sum(1 for r in rows if r["verdict"] in ("доработать", "слабое действие")),
                    "trash": sum(1 for r in rows if r["verdict"] == "тема, не действие")},
    }
    return report


def patch_contract(report, analysis_path=ANALYSIS):
    """Вписывает SMART-отчёт в контракт — дашборд читает только analysis.json.
    Заодно перестраивает commitments из недельного реестра (старый месячный блок
    действий в v3 заменён реестром — фантазии теперь отсюда)."""
    A = json.load(open(analysis_path, encoding="utf-8"))
    A["smart_control"] = report
    commitments = []
    for r in report["rows"]:
        if not r.get("expected"):
            continue
        g = r["checks"]["grounding"]
        verdict = ("фантазия" if g["ok"] is False else
                   "реалистично" if g["ok"] else "не проверяемо")
        commitments.append({
            "manager": r["manager"], "initiative": r["initiative"],
            "expected": round(r["expected"]), "avg_check": g.get("avg_check"),
            "kp_need": g.get("kp_need"), "kp_have": g.get("kp_have"),
            "verdict": verdict, "fact_is_number": False,
        })
    if commitments:
        A["commitments"] = commitments
    json.dump(A, open(analysis_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    rep = run()
    json.dump(rep, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    patch_contract(rep)
    L = ["#" * 78, f"SMART-КОНТРОЛЬ недельного реестра · неделя {rep['as_of']}", "#" * 78]
    s = rep["summary"]
    L.append(f"строк {s['total']} · средний балл {s['avg_score']} · "
             f"конкретно {s['ok']} · доработать {s['rework']} · «тема» {s['trash']}")
    if rep["funnel_week"]["note"]:
        L.append("⚠ " + rep["funnel_week"]["note"])
    for r in rep["rows"]:
        L.append("")
        L.append(f"[{r['score']:>3}] {r['verdict'].upper():<18} {sn(r['manager'])} · «{r['initiative'][:50]}» · {m(r['expected'])}")
        misses = [c["note"] for c in r["checks"].values() if c["note"] and not c["ok"]]
        for n in misses:
            L.append(f"      − {n}")
        if r["rewrite"]:
            L.append(f"      → КАК НАДО: {r['rewrite']}")
    open(TXT, "w", encoding="utf-8").write("\n".join(L))
    print("smart report ->", OUT)
    print("rows:", s["total"], "avg:", s["avg_score"], "| ok/rework/trash:", s["ok"], s["rework"], s["trash"])
