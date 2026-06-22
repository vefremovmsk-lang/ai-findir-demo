# -*- coding: utf-8 -*-
"""
build_dept — унифицированный сборщик КОНТРАКТА отдела (out/<slug>/analysis.json).

Один движок на все отделы. Tier-1 (стандартный лист) разбирается одинаково;
ветвление — по depts.py: формат недельной секции, наличие воронки, радар.

Цепочка:
  extract → diagnosis · calibration · (funnel) · waterfall · seasonality ·
  (radar) → недельный реестр (v3|alt) → SMART + commitments → (ledger) →
  управленческие блоки (alerts · head_urgent · competitors · action_pipeline)

Числа считаются ЗДЕСЬ (детерминированно). LLM/рендереры читают только контракт.
"""
import os
import re
import json
import datetime
from collections import Counter

from extract_v3 import extract
from findir_lab import manager_metrics, funnel_metrics, MONTHS, surname
from context_lib import parse_zero_layer, match_product
import waterfall as WF
import smart_control as SC
import ledger as LED
import v3_register
import weekly_alt
import radar as RAD
from depts import DEPTS, LAB, OUT, CONTROL

# CONTROL (дата контроля) берётся из depts — единый источник для всего движка
ZERO = os.path.join(LAB, "zero_layer.xlsx")

# описания конкурентов (00-слой даёт имена; здесь — короткий контекст)
RIVAL_DESC = {}  # описания конкурентов — заполняются под конкретный рынок


def r0(v):
    return round(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def m(v):
    return f"{v:,.0f}".replace(",", " ") + " ₽" if isinstance(v, (int, float)) else "—"


def sn(f):
    return (f or "").split()[0] if f else ""


def reliability_label(realism):
    if realism is None:
        return "—"
    if realism >= 0.85:
        return "надёжный"
    if realism >= 0.6:
        return "умеренный"
    if realism >= 0.35:
        return "склонен завышать"
    return "хронически завышает"


# --------------------------------------------------------------------------
# блоки контракта
# --------------------------------------------------------------------------

def diagnosis_block(e, cfg):
    q = e.get("quarter") or {}
    cp, cf = q.get("contract_plan"), q.get("contract_fact")
    return {
        "period": cfg.get("period", "Q2 2026"), "control_date": cfg["control_date"],
        "finrez": r0(q.get("finrez")), "revenue_acts": r0(q.get("act_fact")),
        "expenses": r0(q.get("expenses")),
        "deficit_to_zero": r0(-q["finrez"]) if isinstance(q.get("finrez"), (int, float)) else None,
        "contract_plan": r0(cp), "contract_fact": r0(cf),
        "contract_pct": round(cf / cp, 3) if (cp and cf is not None) else None,
        "act_plan": r0(q.get("act_plan")), "act_forecast": r0(q.get("act_forecast")),
    }


def calibration_block(e, closed):
    cal = {}
    for name in e["managers"]:
        mm = manager_metrics(e, name, closed)
        if not (mm["plan"] or mm["fact"]):
            continue
        att = (mm["fact"] / mm["plan"]) if mm["plan"] else None
        real = (mm["fact_where_forecast"] / mm["forecast"]) if mm["forecast"] else None
        cal[name] = {
            "plan": r0(mm["plan"]), "fact": r0(mm["fact"]), "forecast": r0(mm["forecast"]),
            "attainment": round(att, 3) if att is not None else None,
            "forecast_realism": round(real, 3) if real is not None else None,
            "reliability": reliability_label(real),
            "deals": r0(mm["deals"]),
            "avg_check": r0(mm["fact"] / mm["deals"]) if mm["deals"] else None,
        }
    return cal


def funnel_block(e):
    fun = {}
    for name in e["managers"]:
        mm = manager_metrics(e, name, MONTHS)
        fn = funnel_metrics(e, name, MONTHS)
        k2d = (mm["deals"] / fn["kp_fact"]) if fn["kp_fact"] else None
        c2k = (fn["kp_fact"] / fn["calls_fact"]) if fn["calls_fact"] else None
        if not (fn["calls_fact"] or fn["kp_fact"] or mm["deals"]):
            continue
        fun[name] = {
            "calls_fact": r0(fn["calls_fact"]), "kp_fact": r0(fn["kp_fact"]),
            "deals": r0(mm["deals"]), "contract_fact": r0(mm["fact"]),
            "avg_check": r0(mm["fact"] / mm["deals"]) if mm["deals"] else None,
            "conv_call_kp": round(c2k, 3) if c2k is not None else None,
            "conv_kp_deal": round(k2d, 3) if k2d is not None else None,
        }
    return fun


def executors_block(e):
    """Исполнение/актирование по исполнителям (для СМК это 23 аудитора — ядро работы)."""
    def nz(x):
        return x if isinstance(x, (int, float)) and not isinstance(x, bool) else 0.0
    out = []
    for name, md in e["executors"].items():
        mm = md.get("monthly", {})
        plan = sum(nz(mm.get(m, {}).get("act_plan")) for m in MONTHS)
        fact = sum(nz(mm.get(m, {}).get("act_fact")) for m in MONTHS)
        cnt = sum(nz(mm.get(m, {}).get("acts_count")) for m in MONTHS)
        port = sum(nz(mm.get(m, {}).get("portfolio")) for m in MONTHS)
        if not (plan or fact or cnt):
            continue
        out.append({"executor": name, "act_plan": r0(plan), "act_fact": r0(fact),
                    "acts_count": r0(cnt), "portfolio": r0(port),
                    "attainment": round(fact / plan, 3) if plan else None})
    out.sort(key=lambda x: -(x["act_fact"] or 0))
    return out


def seasonality_block(products):
    sp = [{
        "name": p["name"], "strength": p["season"]["strength"],
        "quarters": p["season"]["quarters"], "raw": p["season"]["raw"],
        "cycle": p["cycle"],
        "avg_check": p["avg_check"]["mid"] if isinstance(p.get("avg_check"), dict) else None,
    } for p in products]
    q2 = [s for s in sp if "Q2" in (s["quarters"] or []) and s["strength"] in ("сильная", "слабая", "есть")]
    return {"products": sp, "q2_push": q2}


def eco_radar_block(products):
    """Регуляторный радар экологии из засеянной ленты radar.CALENDAR (офлайн)."""
    push, gaps = [], []
    seen_p, seen_g = set(), set()
    for ev in RAD.CALENDAR:
        kws = ev.get("product_keywords", [])
        matched = [p["name"] for p in products if any(k in p["name"].lower() for k in kws)]
        nd = RAD.next_deadline(ev.get("deadlines", []))
        weeks = (nd - CONTROL).days // 7 if nd else None
        item = {"title": ev["title"][:80], "obligation": ev.get("obligation", ev["title"])[:90],
                "deadline": nd.isoformat() if nd else None, "weeks": weeks,
                "products": matched, "source": ev.get("source")}
        lead = ev.get("lead_weeks", 4)
        if matched and weeks is not None and lead <= weeks <= lead + 5:
            key = (tuple(matched), nd)
            if key not in seen_p:
                seen_p.add(key); push.append(item)
        elif (not matched) and kws and weeks is not None:
            key = ev["title"][:30].lower()
            if key not in seen_g:
                seen_g.add(key); gaps.append(item)
    return {"source": "seed (доменные знания, офлайн)", "push_now": push, "product_gaps": gaps}


# --- недельный реестр → SMART + commitments --------------------------------

_DASH = re.compile(r"[‐-―\-]")   # любые дефисы/тире


def week_end_date(due):
    """Конец недельного периода '01.04-07.04' → date(2026,4,7). Для определения,
    закрыта ли неделя на дату контроля."""
    if not due:
        return None
    parts = _DASH.split(str(due))
    tok = parts[-1].strip() if parts else ""
    mm = re.match(r"(\d{1,2})[.\s](\d{1,2})", tok)
    if not mm:
        return None
    d, mo = int(mm.group(1)), int(mm.group(2))
    try:
        return datetime.date(2026, mo, d)
    except ValueError:
        return None


def smart_and_commitments(reg, A, products, has_funnel):
    funnel_by_surname = {sn(k): v for k, v in (A.get("funnel") or {}).items()}
    convs = [v["conv_kp_deal"] for v in funnel_by_surname.values() if v.get("conv_kp_deal")]
    dept_conv = sum(convs) / len(convs) if convs else None

    rows = [SC.check_row(r, products, funnel_by_surname, dept_conv) for r in reg["register"]]
    fq = SC.funnel_week_quality(reg["funnel_week"])
    avg = round(sum(r["score"] for r in rows) / len(rows)) if rows else None
    report = {
        "as_of": rows[0]["week"] if rows else None,
        "rows": rows, "funnel_week": fq,
        "summary": {"total": len(rows), "avg_score": avg,
                    "ok": sum(1 for r in rows if r["verdict"] == "конкретно"),
                    "rework": sum(1 for r in rows if r["verdict"] in ("доработать", "слабое действие")),
                    "trash": sum(1 for r in rows if r["verdict"] == "тема, не действие")},
    }

    # commitments: ось вердикта зависит от наличия воронки
    commitments, kind = [], ("grounding" if has_funnel else "fact")
    src_rows = reg["register"]
    for r, raw in zip(rows, src_rows):
        exp = r.get("expected")
        if not exp:
            continue
        g = r["checks"]["grounding"]
        fact = raw.get("fact")
        closed = (lambda d: d is not None and d <= CONTROL)(week_end_date(raw.get("due")))
        if has_funnel:
            verdict = ("фантазия" if g["ok"] is False else
                       "реалистично" if g["ok"] else "не проверяемо")
        else:
            if fact is None:
                verdict = "тишина" if closed else "в работе"
            elif fact >= 0.8 * exp:
                verdict = "сбылось"
            elif fact > 0:
                verdict = "частично"
            else:
                verdict = "не сбылось" if closed else "в работе"
        commitments.append({
            "manager": raw.get("manager"), "initiative": r["initiative"],
            "expected": r0(exp), "fact": r0(fact) if fact is not None else None,
            "avg_check": g.get("avg_check"), "kp_need": g.get("kp_need"), "kp_have": g.get("kp_have"),
            "verdict": verdict, "week": raw.get("due"), "closed": closed,
        })
    return report, commitments, kind


# --- управленческие блоки (alerts · urgent · competitors · pipeline) --------

def competitors_block(products, company):
    rivals = Counter()
    by_product = []
    for p in products:
        comps = [c.strip() for c in re.split(r"[,;]", p.get("competitors") or "") if c.strip()]
        for c in comps:
            rivals[c] += 1
        nm = re.sub(r"\s+", " ", (p["name"] or "").replace("\n", " ")).strip()
        by_product.append({"product": (nm[:46] + "…") if len(nm) > 47 else nm,
                           "avg_check": (p["avg_check"] or {}).get("raw") if isinstance(p.get("avg_check"), dict) else None,
                           "competitors": comps})
    top = [{"name": n, "appears": k, "note": RIVAL_DESC.get(n, "")} for n, k in rivals.most_common(7)]
    return {
        "top_rivals": top, "by_product": by_product,
        "our_edge": company.get("Основные преимущества компании"),
        "our_gap": company.get("Основные слабые места компании"),
        "channels": company.get("Какие каналы продаж используем сейчас"),
    }


def management_blocks(A, cfg, commit_kind):
    dg = A["diagnosis"]
    cal = A.get("calibration", {})
    commits = A.get("commitments", [])
    rad = A.get("radar") or {}
    push = sorted([i for i in rad.get("push_now", []) if i.get("weeks") is not None], key=lambda x: x["weeks"])
    nearest = push[0] if push else None
    gaps = sorted([g for g in rad.get("product_gaps", []) if g.get("weeks") is not None and g["weeks"] <= 8],
                  key=lambda x: x["weeks"])

    cpct = dg.get("contract_pct")
    gap_sum = (dg.get("contract_plan") or 0) - (dg.get("contract_fact") or 0)
    unrel = sorted([(sn(n), c["forecast_realism"]) for n, c in cal.items()
                    if c.get("forecast_realism") is not None and c["forecast_realism"] < 0.35],
                   key=lambda x: x[1])
    under = [sn(n) for n, c in cal.items() if (c.get("attainment") or 1) < 0.7]

    if commit_kind == "grounding":
        bad = [c for c in commits if c["verdict"] == "фантазия"]
    else:
        bad = [c for c in commits if c["verdict"] in ("не сбылось", "частично")]
    bad_sum = sum(c["expected"] or 0 for c in bad)

    alerts = []
    if (dg.get("finrez") or 0) < 0:
        alerts.append({"level": "critical", "tag": "Финрез",
                       "text": f"Квартал убыточный: операционный финрез {m(dg['finrez'])}, до нуля не хватает выручки {m(dg['deficit_to_zero'])}."})
    if cpct is not None and cpct < 0.6:
        alerts.append({"level": "critical", "tag": "Контрактация",
                       "text": f"Контрактация {cpct*100:.0f}% плана — разрыв {m(gap_sum)}. Годовой план под угрозой."})
    if bad:
        ex = max(bad, key=lambda c: c["expected"] or 0)
        if commit_kind == "grounding":
            alerts.append({"level": "critical", "tag": "Фантазии",
                           "text": f"{len(bad)} обещаний не подкреплены воронкой на {m(bad_sum)}. Напр. {sn(ex['manager'])}: «{(ex['initiative'] or '')[:34]}» — нужно ~{ex['kp_need']} КП, есть {ex['kp_have']}."})
        else:
            alerts.append({"level": "warn", "tag": "Обещания",
                           "text": f"{len(bad)} недельных обещаний на {m(bad_sum)} закрыты ниже плана/нулём. Напр. {sn(ex['manager'])}: «{(ex['initiative'] or '')[:30]}» обещано {m(ex['expected'])}, факт {m(ex['fact'])}."})
    if under:
        a_lo = min((cal[n]['attainment'] for n in cal if sn(n) in under and cal[n].get('attainment')), default=0) * 100
        alerts.append({"level": "warn", "tag": "План",
                       "text": f"Недобор плана: {', '.join(under)} — выполнение от {a_lo:.0f}%. Пересмотреть план/ресурсы."})
    if unrel:
        names = ", ".join(f"{n} ({r*100:.0f}%)" for n, r in unrel)
        alerts.append({"level": "warn", "tag": "Достоверность",
                       "text": f"Прогнозам не верь напрямую: {names} сбываются ниже 35% — дисконтируй в своде."})
    if nearest:
        alerts.append({"level": "opportunity", "tag": "Дедлайн",
                       "text": f"«{nearest['title']}» через {nearest['weeks']} нед → продавать {', '.join(nearest['products'])} сейчас."})

    head_urgent = []
    if bad:
        head_urgent.append(f"Разобрать {len(bad)} проблемных обещаний на {m(bad_sum)} с менеджерами — вернуть план на землю.")
    if cpct is not None and cpct < 0.6:
        head_urgent.append(f"Добрать контрактацию: разрыв {m(gap_sum)} до плана — иначе годовой план не вытянуть.")
    if nearest:
        head_urgent.append(f"Продавать под дедлайн «{nearest['title']}» (через {nearest['weeks']} нед): {', '.join(nearest['products'])}.")
    if unrel and len(head_urgent) < 3:
        head_urgent.append(f"Дисконтировать прогнозы {', '.join(n for n, _ in unrel)} в своде — иначе квартальный план завышен.")
    if (dg.get("finrez") or 0) < 0 and len(head_urgent) < 3:
        head_urgent.append(f"Закрыть дефицит {m(dg['deficit_to_zero'])} до нуля — направление в операционном минусе.")
    head_urgent = head_urgent[:3]

    pipe = []
    for c in bad[:2]:
        if commit_kind == "grounding":
            pipe.append({"action": f"Разбор с {sn(c['manager'])}: «{(c['initiative'] or '')[:40]}» на {m(c['expected'])}",
                         "owner": "Рук. отдела", "deadline": "эта неделя",
                         "effect": "убрать необоснованное из плана / получить план мероприятий",
                         "basis": f"воронка не вытягивает: нужно ~{c['kp_need']} КП, есть {c['kp_have']}"})
        else:
            pipe.append({"action": f"Разбор с {sn(c['manager'])}: «{(c['initiative'] or '')[:40]}» — обещано {m(c['expected'])}, факт {m(c['fact'])}",
                         "owner": "Рук. отдела", "deadline": "эта неделя",
                         "effect": "понять причину недобора, скорректировать прогноз",
                         "basis": f"неделя {c.get('week')} закрыта ниже плана"})
    if cpct is not None and cpct < 1:
        pipe.append({"action": f"Добрать контрактацию +{m(gap_sum)} до конца квартала", "owner": "РОП",
                     "deadline": "30.06.2026", "effect": "закрыть разрыв плана, выйти из минуса",
                     "basis": f"контрактация {cpct*100:.0f}% плана"})
    if nearest:
        pipe.append({"action": f"Продавать {', '.join(nearest['products'])} под дедлайн «{nearest['title']}»",
                     "owner": "РОП", "deadline": nearest.get("deadline") or f"через {nearest['weeks']} нед",
                     "effect": "выручка под пиковый регуляторный спрос",
                     "basis": f"дедлайн через {nearest['weeks']} нед (радар)"})
    if unrel:
        pipe.append({"action": f"Дисконтировать прогнозы {', '.join(n for n, _ in unrel)} в своде",
                     "owner": "Рук. отдела", "deadline": "при сборке свода",
                     "effect": "реалистичный квартальный прогноз",
                     "basis": f"калибровка: сбываемость {', '.join(f'{r*100:.0f}%' for _, r in unrel)}"})
    pipe.append({"action": f"Добрать выручку под дефицит {m(dg['deficit_to_zero'])} до нуля", "owner": "РОП",
                 "deadline": "30.06.2026", "effect": "выход направления в безубыток",
                 "basis": f"финрез {m(dg['finrez'])}"})
    return alerts, head_urgent, pipe


# --------------------------------------------------------------------------
# главная сборка
# --------------------------------------------------------------------------

def build(slug):
    cfg = DEPTS[slug]
    src = os.path.join(LAB, cfg["file"])
    e = extract(src)

    ctx = parse_zero_layer(ZERO)
    dept = next((v for k, v in ctx["departments"].items() if cfg["zero"] in k.lower()), None)
    products = dept["products"] if dept else []
    company = ctx["company"]

    A = {
        "meta": {"slug": slug, "department": cfg["name"], "title": cfg["title"],
                 "company": (ctx.get("company", {}) or {}).get("Название компании") or "—",
                 "generated_by": "findir unified engine (build_dept)",
                 "source_file": os.path.basename(src),
                 "note": "Числа считает движок; рендереры и LLM читают только этот контракт."},
        "diagnosis": diagnosis_block(e, cfg),
        "calibration": calibration_block(e, cfg["closed"]),
        "seasonality": seasonality_block(products),
    }
    A["waterfall"] = {"finrez_bridge": WF.finrez_bridge(e), "contract_bridge": WF.contract_bridge(e)}
    execs = executors_block(e)
    if execs:
        A["executors"] = execs
    if cfg["has_funnel"]:
        A["funnel"] = funnel_block(e)
    # радар (нужен enrich-у даже пустой)
    A["radar"] = eco_radar_block(products) if cfg["radar"] == "eco" else {
        "source": "—", "push_now": [], "product_gaps": []}

    # недельный реестр → SMART + commitments
    parser = v3_register if cfg["week_format"] == "v3" else weekly_alt
    reg = parser.weekly_register(src)
    report, commitments, commit_kind = smart_and_commitments(reg, A, products, cfg["has_funnel"])
    if reg["register"]:
        A["smart_control"] = report
    A["commitments"] = commitments
    A["commitments_kind"] = commit_kind

    # ledger (только формат v3 — снапшоты копятся по отделу)
    if cfg["has_ledger"] and cfg["week_format"] == "v3":
        LED.LDIR = os.path.join(OUT, slug, "ledger_store")
        LED.snapshot(src)
        led = LED.build()
        if led:
            A["ledger"] = led

    # competitors + управленческие блоки
    A["competitors"] = competitors_block(products, company)
    alerts, urgent, pipe = management_blocks(A, cfg, commit_kind)
    A["alerts"] = alerts
    A["head_urgent"] = urgent
    A["action_pipeline"] = pipe

    outdir = os.path.join(OUT, slug)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "analysis.json")
    json.dump(A, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return A, path


if __name__ == "__main__":
    import sys
    slugs = sys.argv[1:] or list(DEPTS)
    for s in slugs:
        A, path = build(s)
        dg = A["diagnosis"]
        print(f"[{s}] -> {path}")
        print(f"    финрез {m(dg['finrez'])} | контрактация {dg.get('contract_pct') and round(dg['contract_pct']*100)}% "
              f"| дефицит {m(dg['deficit_to_zero'])}")
        print(f"    калибровка: {[(sn(n), c['attainment']) for n, c in A['calibration'].items()]}")
        print(f"    обещаний {len(A['commitments'])} ({A['commitments_kind']}) | "
              f"smart {bool(A.get('smart_control'))} | ledger {bool(A.get('ledger'))} | funnel {bool(A.get('funnel'))}")
        print(f"    алертов {len(A['alerts'])} | конвейер {len(A['action_pipeline'])} | "
              f"конкурентов {len(A['competitors']['top_rivals'])} | сезон-продуктов {len(A['seasonality']['products'])}")
