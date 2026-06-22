# -*- coding: utf-8 -*-
"""
ledger — журнал обещаний во времени (недельный ledger с aging).

Каждый прогон снимает снапшот недельного реестра в store/ledger/week_<дата>.json.
build() склеивает снапшоты по ключу (фамилия · нормализованная инициатива):
  первый раз увидели · сколько недель висит «в работе» · текущий статус · факт.
Aging: 1 нед — норм, 2 — жёлтый, 3+ — красный «висит N-ю неделю».
Патчит analysis.json["ledger"] — дашборд рендерит из контракта.
"""
import json
import os
import re
from v3_register import weekly_register

V3 = r"C:\Users\User\Claude\Projects\ai-findir-lab\UNIT_ЭКОЛОГИЯ_v3.xlsx"
LDIR = r"C:\Users\User\Claude\Projects\ai-findir-lab\store\ledger"
ANALYSIS = r"C:\Users\User\Claude\Projects\ai-findir-lab\analysis.json"

CLOSED_WORDS = ("выполнен", "закрыт", "сделан", "готово", "отменен", "отменён", "снят")


def sn(full):
    return (full or "").split()[0]


def norm_key(manager, initiative):
    ini = re.sub(r"[^\wа-яё ]", "", (initiative or "").lower())
    ini = re.sub(r"\s+", " ", ini).strip()
    return f"{sn(manager).lower()}::{ini}"


def snapshot(path=V3):
    """Снимает текущую неделю реестра в store/ledger/."""
    os.makedirs(LDIR, exist_ok=True)
    reg = weekly_register(path)["register"]
    if not reg:
        return None
    week = next((r.get("week") for r in reg if r.get("week")), "unknown")
    fp = os.path.join(LDIR, f"week_{week}.json")
    json.dump({"week": week, "rows": reg}, open(fp, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return fp


def build():
    """Склеивает все недельные снапшоты в ledger."""
    files = sorted(f for f in os.listdir(LDIR) if f.startswith("week_")) if os.path.isdir(LDIR) else []
    weeks = [json.load(open(os.path.join(LDIR, f), encoding="utf-8")) for f in files]
    if not weeks:
        return None
    items = {}
    for w in weeks:
        for r in w["rows"]:
            if not r.get("initiative"):
                continue
            k = norm_key(r.get("manager"), r.get("initiative"))
            it = items.setdefault(k, {
                "manager": r.get("manager"), "initiative": r.get("initiative"),
                "first_week": w["week"], "history": []})
            it["history"].append({"week": w["week"], "status": r.get("status"),
                                  "expected": r.get("expected"), "fact": r.get("fact")})
    rows = []
    last_week = weeks[-1]["week"]
    for k, it in items.items():
        h = it["history"]
        cur = h[-1]
        status = (cur.get("status") or "").lower()
        closed = any(wd in status for wd in CLOSED_WORDS) or cur.get("fact") is not None
        open_weeks = sum(1 for x in h if not (
            any(wd in (x.get("status") or "").lower() for wd in CLOSED_WORDS) or x.get("fact") is not None))
        in_current = cur["week"] == last_week
        rows.append({
            "manager": it["manager"], "initiative": it["initiative"],
            "first_week": it["first_week"], "weeks_open": open_weeks,
            "status_now": cur.get("status"), "expected": cur.get("expected"),
            "fact": cur.get("fact"), "closed": closed,
            "vanished": not in_current and not closed,  # пропало из реестра без закрытия
        })
    rows.sort(key=lambda r: (-r["weeks_open"], -(r["expected"] or 0)))
    summary = {
        "weeks_tracked": len(weeks), "current_week": last_week,
        "open": sum(1 for r in rows if not r["closed"] and not r["vanished"]),
        "stuck": sum(1 for r in rows if r["weeks_open"] >= 3 and not r["closed"]),
        "closed": sum(1 for r in rows if r["closed"]),
        "vanished": sum(1 for r in rows if r["vanished"]),
        "new_this_week": sum(1 for r in rows if r["first_week"] == last_week),
        "promised_open_sum": round(sum(r["expected"] or 0 for r in rows
                                       if not r["closed"] and not r["vanished"])),
    }
    return {"summary": summary, "rows": rows}


def patch_contract(ledger, analysis_path=ANALYSIS):
    A = json.load(open(analysis_path, encoding="utf-8"))
    A["ledger"] = ledger
    json.dump(A, open(analysis_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    fp = snapshot()
    led = build()
    if led:
        patch_contract(led)
        s = led["summary"]
        print("snapshot ->", fp)
        print(f"ledger: недель {s['weeks_tracked']} | открыто {s['open']} на {s['promised_open_sum']} руб | "
              f"висят 3+ нед {s['stuck']} | закрыто {s['closed']} | пропало {s['vanished']} | новых {s['new_this_week']}")
    else:
        print("ledger: нет снапшотов")
