# -*- coding: utf-8 -*-
"""
waterfall — план-факт мост (мировой стандарт FP&A: variance analysis).

Мост 1 «финрез»: старт = финрез при плановом актировании (act_plan − expenses),
шаги = недобор актирования по месяцам, финиш = фактический финрез.
Мост 2 «контрактация»: план → факт по менеджерам (кто сколько недодал).
Патчит analysis.json["waterfall"].
"""
import json
from extract_v3 import extract
from findir_lab import manager_metrics, MONTHS

V3 = r"C:\Users\User\Claude\Projects\ai-findir-lab\UNIT_ЭКОЛОГИЯ_v3.xlsx"
ANALYSIS = r"C:\Users\User\Claude\Projects\ai-findir-lab\analysis.json"
RU_MON = {"april": "апрель", "may": "май", "june": "июнь"}


def r0(v):
    return round(v) if isinstance(v, (int, float)) else None


def finrez_bridge(e):
    q = e["quarter"]
    start = q["act_plan"] - q["expenses"]          # финрез, будь акты по плану
    steps = []
    for mk in ("april", "may", "june"):
        md = e["monthly"][mk]
        delta = (md["act_fact"] or 0) - (md["act_plan"] or 0)
        steps.append({"label": f"акты {RU_MON[mk]}", "delta": r0(delta),
                      "note": ("месяц открыт; прогноз актов "
                               f"{r0(md.get('act_forecast')) or 0:,}".replace(",", " ") + " ₽"
                               if mk == "june" else None)})
    end = q["finrez"]
    drift = end - (start + sum(s["delta"] for s in steps))
    if abs(drift) > 1000:   # необъяснённый остаток (расхождения сводки) — показываем честно
        steps.append({"label": "прочее/сводка", "delta": r0(drift), "note": None})
    return {"start": {"label": "финрез при плановых актах", "value": r0(start)},
            "steps": steps,
            "end": {"label": "финрез факт", "value": r0(end)},
            "reading": (f"При плановом актировании квартал был бы "
                        f"{'+' if start >= 0 else ''}{r0(start):,} ₽".replace(",", " ") +
                        "; весь минус — недобор актов.")}


def contract_bridge(e):
    q = e["quarter"]
    rows = []
    for name in e["managers"]:
        mm = manager_metrics(e, name, MONTHS)
        if not (mm["plan"] or mm["fact"]):
            continue
        rows.append({"manager": name, "plan": r0(mm["plan"]), "fact": r0(mm["fact"]),
                     "delta": r0((mm["fact"] or 0) - (mm["plan"] or 0))})
    rows.sort(key=lambda r: r["delta"])
    return {"plan": r0(q["contract_plan"]), "fact": r0(q["contract_fact"]),
            "delta": r0(q["contract_fact"] - q["contract_plan"]), "by_manager": rows}


if __name__ == "__main__":
    e = extract(V3)
    wf = {"finrez_bridge": finrez_bridge(e), "contract_bridge": contract_bridge(e)}
    A = json.load(open(ANALYSIS, encoding="utf-8"))
    A["waterfall"] = wf
    json.dump(A, open(ANALYSIS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    fb = wf["finrez_bridge"]
    print("start:", fb["start"]["value"], "| steps:", [(s["label"], s["delta"]) for s in fb["steps"]],
          "| end:", fb["end"]["value"])
    cb = wf["contract_bridge"]
    print("contract plan->fact:", cb["plan"], "->", cb["fact"],
          "| by mgr:", [(r["manager"].split()[0], r["delta"]) for r in cb["by_manager"]])
