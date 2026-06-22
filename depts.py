# -*- coding: utf-8 -*-
"""
depts — реестр отделов для унифицированного движка AI-Findir.

Один движок (build_dept → dash → anonymize → owner) обслуживает все отделы; различия
вынесены сюда. Tier-1 (стандартный лист) одинаков у всех; отличаются формат недельной
секции, наличие воронки/реестра сделок и регуляторного радара.

АВТО-РЕЖИМ (чтобы не править руками каждую неделю):
  • файл отдела ищется по шаблону в raw/ — берётся САМЫЙ СВЕЖИЙ по дате в имени
    (формат имени: <prefix>_q<N>_<YYYY>_<MMDD>.xlsx). Старые выгрузки можно не удалять.
  • CONTROL_DATE и период (Q/год) выводятся из имени выбранного файла.
  • closed (закрытые месяцы) = месяцы квартала ДО месяца контроля.
Просто положи новые xlsx в raw/ и запусти run_all.py — пути/дату трогать не нужно.

  week_format: "v3"  — Экология: 5.1/5.2 «Недельный реестр» + секция 6 «Воронка»
               "alt" — Прод/УЦ/СМК: «Недельные действия» (продажи+исполнение в одной таблице)
  zero        — подстрока ключа отдела в zero_layer.xlsx (00-слой: продукты/конкуренты/сезон)
  radar       — "eco" (регуляторный календарь экологии) | None
"""
import os
import re
import glob
import datetime

LAB = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(LAB, "out")
RAW = os.path.join(LAB, "raw")

MONTHS_EN = {1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
             7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december"}

# имя выгрузки: <prefix>_q<N>_<YYYY>_<MMDD>.xlsx  (напр. ecology_q2_2026_0619.xlsx)
_NAME_RX = re.compile(r"_q(\d)_(\d{4})_(\d{2})(\d{2})\.xlsx$", re.IGNORECASE)


def _parse_name(path):
    """-> (quarter:int, date) или None, если имя не по формату."""
    m = _NAME_RX.search(os.path.basename(path))
    if not m:
        return None
    q, y, mm, dd = (int(x) for x in m.groups())
    try:
        return q, datetime.date(y, mm, dd)
    except ValueError:
        return None


def resolve_latest(prefix):
    """Самый свежий файл отдела в raw/ по дате в имени (fallback — mtime файла)."""
    cands = sorted(glob.glob(os.path.join(RAW, f"{prefix}_*.xlsx")))
    if not cands:
        return None, None, None
    parsed = [(p, _parse_name(p)) for p in cands]
    dated = [(p, pr) for p, pr in parsed if pr]
    if dated:
        path, (q, d) = max(dated, key=lambda x: x[1][1])
        return os.path.relpath(path, LAB), q, d
    path = max(cands, key=os.path.getmtime)            # имена не по формату — берём новейший по mtime
    return os.path.relpath(path, LAB), None, None


# ---- сиды отделов: шаблон имени в raw/ + статические различия ----
_SEED = {
    "eco":  {"prefix": "ecology",              "name": "Экологические услуги",      "title": "Экология",
             "zero": "колог", "week_format": "v3",  "has_funnel": True,  "has_ledger": True,  "radar": "eco"},
    "prod": {"prefix": "product_certification","name": "Сертификация продукции",     "title": "Сертификация продукции",
             "zero": "продукц","week_format": "alt", "has_funnel": False, "has_ledger": False, "radar": None},
    "uc":   {"prefix": "training_center",      "name": "Учебный центр",             "title": "Учебный центр",
             "zero": "учеб",  "week_format": "alt", "has_funnel": False, "has_ledger": False, "radar": None},
    "smk":  {"prefix": "qms",                  "name": "Сертификация СМК (ОССМ)",   "title": "Сертификация СМК",
             "zero": "смк",   "week_format": "alt", "has_funnel": False, "has_ledger": False, "radar": None},
}

ORDER = ["eco", "prod", "uc", "smk"]

# ---- авто-резолв файлов + единая дата контроля по всему движку ----
_resolved = {slug: resolve_latest(s["prefix"]) for slug, s in _SEED.items()}
_dates = [d for (_f, _q, d) in _resolved.values() if d]
_quarters = [q for (_f, q, _d) in _resolved.values() if q]

CONTROL = max(_dates) if _dates else datetime.date.today()        # дата для ЛОГИКИ (build_dept)
CONTROL_DATE = CONTROL.isoformat()                                # строка для дисплея
_Q = _quarters[0] if _quarters else (CONTROL.month - 1) // 3 + 1
PERIOD = f"Q{_Q} {CONTROL.year}"

# закрытые месяцы = месяцы текущего квартала ДО месяца контроля (июнь открыт на контроль в июне)
_q_months = [(_Q - 1) * 3 + i for i in (1, 2, 3)]
CLOSED_MONTHS = [MONTHS_EN[m] for m in _q_months if m < CONTROL.month]

DEPTS = {}
for slug in ORDER:
    s = _SEED[slug]
    f, _q, _d = _resolved[slug]
    DEPTS[slug] = {
        "slug": slug, "name": s["name"], "title": s["title"],
        "file": f,                              # относительный путь к свежему xlsx (или None, если не найден)
        "zero": s["zero"], "week_format": s["week_format"],
        "has_funnel": s["has_funnel"], "has_ledger": s["has_ledger"], "radar": s["radar"],
        "control_date": CONTROL_DATE, "period": PERIOD, "closed": CLOSED_MONTHS,
    }


if __name__ == "__main__":
    print(f"CONTROL={CONTROL_DATE} | PERIOD={PERIOD} | closed={CLOSED_MONTHS}")
    for slug in ORDER:
        print(f"  {slug:5} -> {DEPTS[slug]['file']}")
