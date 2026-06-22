# -*- coding: utf-8 -*-
"""
findir_lab — движок фундамента (прототип, lab).

Содержит:
  - метрики по менеджерам (план/факт/прогноз контрактации, сделки, воронка, ср.чек);
  - обоснование обязательств (grounding) — обещанный эффект против воронки;
  - снимок периода для хранилища (store);
  - калибровку достоверности руководителей (план→факт, прогноз→факт).

Зависит только от extract_v3 (стандартная библиотека).
"""
from __future__ import annotations
import json
from extract_v3 import extract

MONTHS = ["april", "may", "june"]
RU = {"april": "Апрель", "may": "Май", "june": "Июнь"}


def n(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else 0.0


def closed_months(control_month: str) -> list:
    if control_month not in MONTHS:
        return MONTHS[:]
    return MONTHS[:MONTHS.index(control_month)]


# ---------------------------------------------------------------------------
# Метрики по менеджеру
# ---------------------------------------------------------------------------

def manager_metrics(e: dict, name: str, months: list) -> dict:
    md = e["managers"].get(name, {}).get("monthly", {})
    plan = sum(n(md.get(m, {}).get("contract_plan")) for m in months)
    fact = sum(n(md.get(m, {}).get("contract_fact")) for m in months)
    # прогноз: учитываем только месяцы, где он задан ПОЛОЖИТЕЛЬНЫМ числом.
    # forecast == 0 — это незаполненная ячейка, а не реальный прогноз; включать её
    # нельзя (иначе fact попадает в числитель, а 0 в знаменатель -> перекос сбываемости).
    fc_pairs = []
    for m in months:
        fc = md.get(m, {}).get("contract_forecast")
        if isinstance(fc, (int, float)) and not isinstance(fc, bool) and fc > 0:
            fc_pairs.append((fc, n(md.get(m, {}).get("contract_fact"))))
    forecast = sum(f for f, _ in fc_pairs)
    fact_where_fc = sum(fa for _, fa in fc_pairs)
    deals = sum(n(md.get(m, {}).get("deals_count")) for m in months)
    return {"plan": plan, "fact": fact, "forecast": forecast,
            "fact_where_forecast": fact_where_fc, "deals": deals}


def funnel_metrics(e: dict, name: str, months: list) -> dict:
    calls = e["funnel"].get("calls", {}).get(name, {})
    kp = e["funnel"].get("kp", {}).get(name, {})
    cf = sum(n(calls.get(m, {}).get("fact")) for m in months)
    kf = sum(n(kp.get(m, {}).get("fact")) for m in months)
    return {"calls_fact": cf, "kp_fact": kf}


def avg_check(e: dict, name: str, months: list) -> float | None:
    mm = manager_metrics(e, name, months)
    return mm["fact"] / mm["deals"] if mm["deals"] else None


# ---------------------------------------------------------------------------
# Обоснование обязательств (grounding)
# ---------------------------------------------------------------------------

def surname(full: str) -> str:
    return (full or "").split()[0] if full else ""


def ground_commitments(e: dict, months: list = MONTHS) -> list:
    """Каждой инициативе из блока действий — арифметическая проверка по воронке."""
    out = []
    for a in e["actions"]:
        sa = a.get("sales")
        if not sa or not (sa.get("initiative") or sa.get("manager")):
            continue
        mgr_raw = sa.get("manager")
        full = next((nm for nm in e["managers"] if surname(nm) == surname(mgr_raw) or nm == mgr_raw), mgr_raw)
        exp = sa.get("expected_contract")
        exp = exp if isinstance(exp, (int, float)) else None
        ac = avg_check(e, full, months)
        fm = funnel_metrics(e, full, months)
        mm = manager_metrics(e, full, months)
        k2d = (mm["deals"] / fm["kp_fact"]) if fm["kp_fact"] else None
        implied_deals = (exp / ac) if (exp and ac) else None
        implied_kp = (implied_deals / k2d) if (implied_deals and k2d) else None
        # статус: фантазия, если для эффекта нужно КП больше, чем есть в воронке (с запасом x1.5)
        status = "нет числа"
        if exp is not None:
            if implied_kp is None:
                status = "нет воронки"
            elif implied_kp <= fm["kp_fact"]:
                status = "реалистично"
            elif implied_kp <= fm["kp_fact"] * 1.5:
                status = "на пределе"
            else:
                status = "фантазия"
        fact_raw = sa.get("fact_contract")
        fact_is_number = isinstance(fact_raw, (int, float))
        out.append({
            "manager": mgr_raw, "initiative": sa.get("initiative"),
            "expected": exp, "avg_check": ac, "kp_have": fm["kp_fact"],
            "kp2deal": k2d, "implied_deals": implied_deals, "implied_kp": implied_kp,
            "status": status, "fact_raw": fact_raw, "fact_is_number": fact_is_number,
        })
    return out


# ---------------------------------------------------------------------------
# Снимок периода для хранилища
# ---------------------------------------------------------------------------

def build_snapshot(path: str, label: str, control_month: str) -> dict:
    e = extract(path)
    cl = closed_months(control_month)
    managers = {}
    for name in e["managers"]:
        mm_all = manager_metrics(e, name, MONTHS)
        mm_closed = manager_metrics(e, name, cl)
        fn = funnel_metrics(e, name, cl)
        managers[name] = {
            "closed": mm_closed, "quarter": mm_all,
            "funnel_closed": fn, "avg_check_closed": avg_check(e, name, cl),
        }
    return {
        "label": label, "control_month": control_month, "closed_months": cl,
        "department": "ecology", "period": "2026_q2",
        "monthly": e["monthly"], "quarter": e.get("quarter"),
        "managers": managers,
        "commitments": ground_commitments(e),
        "deals_count": len(e["deals"]),
        "source_file": path,
    }


# ---------------------------------------------------------------------------
# Калибровка достоверности
# ---------------------------------------------------------------------------

def reliability_label(realism: float | None) -> str:
    if realism is None:
        return "—"
    if realism >= 0.85:
        return "надёжный"
    if realism >= 0.6:
        return "умеренный"
    if realism >= 0.35:
        return "склонен завышать"
    return "хронически завышает"


def calibrate(snapshots: list) -> dict:
    """По закрытым месяцам: attainment (факт/план) и realism (факт/прогноз) на менеджера.
    Берём самый свежий снимок как источник закрытых месяцев (он полнее)."""
    latest = snapshots[-1]
    out = {}
    for name, md in latest["managers"].items():
        c = md["closed"]
        attain = (c["fact"] / c["plan"]) if c["plan"] else None
        realism = (c["fact_where_forecast"] / c["forecast"]) if c["forecast"] else None
        out[name] = {
            "plan": c["plan"], "fact": c["fact"], "forecast": c["forecast"],
            "attainment": attain, "forecast_realism": realism,
            "reliability": reliability_label(realism),
            "deals": c["deals"], "avg_check": md["avg_check_closed"],
        }
    return out
