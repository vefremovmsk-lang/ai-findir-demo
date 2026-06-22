# -*- coding: utf-8 -*-
"""
v3_register — парсер недельных секций файла v3:
  5. Недельный реестр обязательств и действий (Неделя·Менеджер·Инициатива·Рычаг·
     Продукт·Клиент/сделка·Ожид.₽·Срок(нед)·Статус·Факт₽)
  6. Недельная воронка (Неделя·Менеджер·Звонки·КП·Встречи)
"""
import re
from extract_v3 import load_sheets, find_main_sheet

REG_COLS = {"неделя": "week", "менеджер": "manager", "исполнитель": "manager",
            "инициатива": "initiative",
            "рычаг": "lever", "продукт": "product", "клиент": "client",
            "ожид": "expected", "срок": "due", "статус": "status", "факт": "fact"}

_HDR_WORDS = {"менеджер", "исполнитель", "инициатива", "неделя"}
FUN_COLS = {"неделя": "week", "менеджер": "manager", "звонки": "calls",
            "кп": "kp", "встречи": "meets"}


def _t(v):
    s = str(v).strip() if v is not None else ""
    return s or None


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        s = v.replace(" ", "").replace(" ", "").replace(",", ".")
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            return float(s)
    return None


def _section_rows(grid, title_kw, colmap):
    """Находит секцию по ключу в заголовке, маппит колонки по подписям, отдаёт строки.
    Заголовок колонок ищется не «через строку», а сканом ниже названия секции —
    между названием и шапкой может стоять под-строка месяца (Апрель/Май/Июнь)."""
    maxr = max(r for r, _ in grid)
    start = None
    for (r, c), v in sorted(grid.items()):
        if c == 1 and isinstance(v, str) and title_kw in v.lower():
            start = r
            break
    if start is None:
        return [], None
    # шапка = строка ниже названия с максимумом совпадений подписей колонок
    hdr, best = None, 0
    for rr in range(start + 1, min(start + 8, maxr) + 1):
        cnt = sum(1 for c in range(1, 30)
                  if (_t(grid.get((rr, c))) or "") and
                  any(kw in _t(grid.get((rr, c))).lower() for kw in colmap))
        if cnt > best:
            best, hdr = cnt, rr
        if cnt >= 3:
            break
    if hdr is None or best < 2:
        return [], None
    cols = {}
    for c in range(1, 30):
        h = _t(grid.get((hdr, c)))
        if not h:
            continue
        for kw, key in colmap.items():
            if kw in h.lower() and key not in cols:
                cols[key] = c
    rows = []
    for r in range(hdr + 1, maxr + 1):
        first = _t(grid.get((r, 1)))
        # стоп на следующей секции («N. Название»)
        if first and re.match(r"^\d+\.\s", first):
            break
        row = {key: grid.get((r, c)) for key, c in cols.items()}
        if not any(_t(x) for x in row.values()):
            continue
        rows.append({"row": r, **{k: _t(v) if k not in ("expected", "fact", "calls", "kp", "meets")
                                  else _num(v) for k, v in row.items()}})
    return rows, hdr


def weekly_register(path):
    sheets = load_sheets(path)
    grid = sheets[find_main_sheet(sheets)]
    reg, _ = _section_rows(grid, "недельный реестр", REG_COLS)
    fun, _ = _section_rows(grid, "воронка", FUN_COLS)
    # неделя как ISO-дата если парсится
    for r in reg + fun:
        w = r.get("week")
        if w and re.match(r"^\d{4}-\d{2}-\d{2}", str(w)):
            r["week"] = str(w)[:10]
    # выбрасываем строки без менеджера/инициативы и просочившиеся строки-шапки
    def _is_hdr(r):
        return (str(r.get("manager") or "").strip().lower() in _HDR_WORDS or
                str(r.get("initiative") or "").strip().lower() in _HDR_WORDS)
    reg = [r for r in reg if (r.get("manager") or r.get("initiative")) and not _is_hdr(r)]
    fun = [r for r in fun if r.get("manager") and not _is_hdr(r)]
    return {"register": reg, "funnel_week": fun}


if __name__ == "__main__":
    import json
    res = weekly_register(r"C:\Users\User\Claude\Projects\ai-findir-lab\UNIT_ЭКОЛОГИЯ_v3.xlsx")
    json.dump(res, open(r"C:\Users\User\Claude\Projects\ai-findir-lab\insp_register.json", "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    print("register rows:", len(res["register"]), "| funnel rows:", len(res["funnel_week"]))
