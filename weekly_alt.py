# -*- coding: utf-8 -*-
"""
weekly_alt — парсер недельной секции 5 в «совмещённом» формате (отделы
Сертификация продукции и Учебный центр):

  5. Недельные действия / инициативы продаж и исполнения
  Блок · Период · Менеджер · Действие · Инициатива · Ожид.эффект контрактации ·
  Факт эффект контрактации · Исполнитель · Инициатива исполнения ·
  Ожид.эффект исполнения · Факт эффект исполнения

Отличается от формата экологии (там 5.1/5.2 «Недельный реестр» + отдельная
секция 6 «Воронка», их разбирает v3_register). Здесь обе стороны (продажи и
исполнение) в одной таблице, ожидаемый ₽ — в 6-й колонке.

Возвращает тот же контракт, что и v3_register.weekly_register:
  {"register": [...], "funnel_week": []}
строки совместимы со smart_control.check_row (ключи initiative/expected/due/
product/client/lever/manager/week/status/fact). Воронки недели тут нет.
"""
import re
from extract_v3 import load_sheets, find_main_sheet

# подписи колонок → ключ строки (берётся ПЕРВОЕ совпадение слева направо,
# поэтому «ожид…контрактации» (продажи) выигрывает у «ожид…исполнения»)
COLMAP = [
    ("период", "due"),          # период недели = срок результата
    ("менеджер", "manager"),
    ("инициатива", "initiative"),
    ("ожид", "expected"),
    ("факт", "fact"),
]


def _t(v):
    s = str(v).strip() if v is not None else ""
    return s or None


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        s = v.replace(" ", "").replace(" ", "").replace(",", ".")
        m = re.match(r"-?\d+(\.\d+)?", s)   # берём ведущее число («20000»,«250000+5000000»→первое)
        if m:
            return float(m.group(0))
    return None


def _find_section5(grid):
    maxr = max(r for r, _ in grid)
    start = None
    for r in range(1, maxr + 1):
        v = grid.get((r, 1))
        if isinstance(v, str) and re.match(r"^5\.", v.strip()):
            start = r
            break
    return start, maxr


def weekly_register(path):
    sheets = load_sheets(path)
    grid = sheets[find_main_sheet(sheets)]
    start, maxr = _find_section5(grid)
    if start is None:
        return {"register": [], "funnel_week": []}

    hdr = start + 1
    cols = {}
    for c in range(1, 16):
        h = _t(grid.get((hdr, c)))
        if not h:
            continue
        lo = h.lower()
        for kw, key in COLMAP:
            if kw in lo and key not in cols:
                cols[key] = c
    if "manager" not in cols or "initiative" not in cols:
        return {"register": [], "funnel_week": []}

    reg = []
    for r in range(hdr + 1, maxr + 1):
        first = _t(grid.get((r, 1)))
        if first and re.match(r"^\d+\.\s", first):   # следующая секция
            break
        manager = _t(grid.get((r, cols["manager"])))
        initiative = _t(grid.get((r, cols.get("initiative", 0))))
        expected = _num(grid.get((r, cols.get("expected", 0))))
        fact = _num(grid.get((r, cols.get("fact", 0))))
        due = _t(grid.get((r, cols.get("due", 0))))
        if not manager and not initiative:
            continue
        if not manager:            # строка-продолжение без менеджера — пропускаем
            continue
        reg.append({
            "row": r, "week": due, "manager": manager, "initiative": initiative,
            "lever": None, "product": None, "client": None,
            "expected": expected, "due": due, "status": None, "fact": fact,
        })
    return {"register": reg, "funnel_week": []}


if __name__ == "__main__":
    import json
    for f in ("raw/product_certification_q2_2026_0611.xlsx",
              "raw/training_center_q2_2026_0611.xlsx"):
        res = weekly_register(f)
        print(f"\n{f.split('/')[-1]}: register={len(res['register'])}")
        for r in res["register"][:6]:
            print(f"   {r['manager']:<10} | {(r['initiative'] or '')[:40]:<40} "
                  f"| exp={r['expected']} fact={r['fact']} due={r['week']}")
