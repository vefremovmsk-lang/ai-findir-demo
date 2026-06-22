# -*- coding: utf-8 -*-
"""
Экстрактор v3 (прототип, lab) — читает реальный файл юнит-экономики.

Tier 1 (Стандарт, обязательный): первый лист — 5 секций.
Tier 2 (Доказательство, опциональный): листы 'Договора' и 'КП и Звонки', если есть.

Зависимостей нет: .xlsx читается как zip+xml стандартной библиотекой.
Колонки первого листа фиксированы (лист единый для всех отделов);
строки/секции находятся динамически (у отделов разное число людей).
"""
from __future__ import annotations
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

MONTHS = ["april", "may", "june"]


# ---------------------------------------------------------------------------
# Низкоуровневое чтение .xlsx (zip + xml), без openpyxl
# ---------------------------------------------------------------------------

def _ln(tag: str) -> str:
    return tag.split('}')[-1]


def _col_to_num(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


_REF = re.compile(r'([A-Z]+)(\d+)')


def load_sheets(path: str) -> dict:
    """Возвращает {sheet_name: grid}, где grid[(row, col)] = value (1-indexed)."""
    z = zipfile.ZipFile(path)
    names = set(z.namelist())

    shared = []
    if 'xl/sharedStrings.xml' in names:
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in root:
            shared.append(''.join(t.text or '' for t in si.iter() if _ln(t.tag) == 't'))

    wb = ET.fromstring(z.read('xl/workbook.xml'))
    defs = []
    for el in wb.iter():
        if _ln(el.tag) == 'sheet':
            rid = None
            for k, v in el.attrib.items():
                if k.split('}')[-1] == 'id':
                    rid = v
            defs.append((el.attrib.get('name'), rid))

    rels = {}
    if 'xl/_rels/workbook.xml.rels' in names:
        rr = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        for rel in rr:
            rels[rel.attrib['Id']] = rel.attrib['Target']

    sheets = {}
    for name, rid in defs:
        target = rels.get(rid, '')
        path_in = target if target.startswith('xl/') else 'xl/' + target.lstrip('/')
        if path_in not in names:
            cand = [n for n in names if n.endswith(target.split('/')[-1])]
            if not cand:
                continue
            path_in = cand[0]
        sroot = ET.fromstring(z.read(path_in))
        grid = {}
        for c in sroot.iter():
            if _ln(c.tag) != 'c':
                continue
            ref = c.attrib.get('r', '')
            t = c.attrib.get('t')
            raw = None
            for ch in c:
                if _ln(ch.tag) == 'v':
                    raw = ch.text
                elif _ln(ch.tag) == 'is':
                    raw = ''.join(tt.text or '' for tt in ch.iter() if _ln(tt.tag) == 't')
                    t = 'inlineStr'
            if raw is None:
                continue
            if t == 's':
                try:
                    val = shared[int(raw)]
                except (ValueError, IndexError):
                    val = raw
            elif t in ('inlineStr', 'str', 'b'):
                val = raw
            else:
                try:
                    val = int(raw) if re.fullmatch(r'-?\d+', raw) else float(raw)
                except ValueError:
                    val = raw
            m = _REF.match(ref)
            if not m:
                continue
            grid[(int(m.group(2)), _col_to_num(m.group(1)))] = val
        sheets[name] = grid
    return sheets


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def month_key(s) -> str | None:
    if s is None:
        return None
    lo = str(s).strip().lower()
    if 'апрел' in lo:
        return 'april'
    if 'май' in lo or 'мая' in lo:
        return 'may'
    if 'июн' in lo:
        return 'june'
    return None


def is_quarter_total(s) -> bool:
    lo = str(s or '').lower()
    return 'итого' in lo or ('q2' in lo and 'квартал' not in lo) or lo.strip() == 'q2 итого'


_HEADER_WORDS = {'менеджер', 'месяц', 'исполнитель', 'неделя', 'период', 'итого', 'блок', 'сотрудник'}


# ---------------------------------------------------------------------------
# Поиск секций первого листа
# ---------------------------------------------------------------------------

_SECTIONS = [
    ('svod',      lambda s: s.startswith('1.') and 'свод' in s.lower()),
    ('managers',  lambda s: s.startswith('2.') and ('продаж' in s.lower() or 'контракт' in s.lower())),
    ('executors', lambda s: s.startswith('3.') and ('исполн' in s.lower() or 'актир' in s.lower())),
    ('expenses',  lambda s: s.startswith('4.') and 'расход' in s.lower()),
    ('actions',   lambda s: s.startswith('5.') and ('действ' in s.lower() or 'инициатив' in s.lower() or 'недел' in s.lower())),
]


def find_sections(grid: dict, max_row: int) -> dict:
    found = {}
    for r in range(1, max_row + 1):
        v = grid.get((r, 1))
        if v is None:
            continue
        s = str(v).strip()
        for name, match in _SECTIONS:
            if name not in found and match(s):
                found[name] = r
    ordered = sorted(found.items(), key=lambda x: x[1])
    bounds = {}
    for i, (name, row) in enumerate(ordered):
        end = ordered[i + 1][1] - 1 if i + 1 < len(ordered) else max_row
        bounds[name] = (row + 2, end)  # данные начинаются через строку-заголовок
    return bounds


def max_row_of(grid: dict) -> int:
    return max((r for (r, _c) in grid), default=0)


# ---------------------------------------------------------------------------
# Парсинг первого листа (Tier 1)
# ---------------------------------------------------------------------------

def parse_main(grid: dict, warnings: list) -> dict:
    mr = max_row_of(grid)
    sec = find_sections(grid, mr)
    missing = [s for s in ('svod', 'managers', 'executors', 'expenses', 'actions') if s not in sec]
    if missing:
        warnings.append(f"первый лист: не найдены секции {missing}")

    def g(r, c):
        return grid.get((r, c))

    # --- 1. Свод по месяцам --- (A=1..N=14)
    monthly, quarter = {}, None
    if 'svod' in sec:
        a, b = sec['svod']
        for r in range(a, b + 1):
            label = g(r, 1)
            row = {
                "contract_plan": num(g(r, 2)), "contract_fact": num(g(r, 3)),
                "contract_forecast": num(g(r, 4)), "contract_pct": num(g(r, 5)),
                "act_plan": num(g(r, 6)), "act_fact": num(g(r, 7)),
                "act_forecast": num(g(r, 8)), "portfolio": num(g(r, 9)),
                "expenses": num(g(r, 10)), "finrez": num(g(r, 11)),
                "margin": num(g(r, 12)), "init_effect_sales": num(g(r, 13)),
                "init_effect_exec": num(g(r, 14)),
            }
            mk = month_key(label)
            if mk:
                monthly[mk] = row
            elif is_quarter_total(label):
                quarter = row

    # --- 2. Продажи / контрактация по менеджерам --- (A=month B=name C..K)
    managers = {}
    if 'managers' in sec:
        a, b = sec['managers']
        for r in range(a, b + 1):
            mk = month_key(g(r, 1))
            name = text(g(r, 2))
            if not mk or not name or name.lower() in _HEADER_WORDS:
                continue
            managers.setdefault(name, {"monthly": {}})["monthly"][mk] = {
                "contract_plan": num(g(r, 3)), "contract_fact": num(g(r, 4)),
                "contract_forecast": num(g(r, 5)), "on_signing": num(g(r, 6)),
                "deviation": num(g(r, 7)), "pct": num(g(r, 8)),
                "deals_count": num(g(r, 9)), "init_effect": num(g(r, 10)),
                "status": text(g(r, 11)),
            }

    # --- 3. Исполнение / актирование по исполнителям --- (A=month B=name C..K)
    executors = {}
    if 'executors' in sec:
        a, b = sec['executors']
        for r in range(a, b + 1):
            mk = month_key(g(r, 1))
            name = text(g(r, 2))
            if not mk or not name or name.lower() in _HEADER_WORDS:
                continue
            executors.setdefault(name, {"monthly": {}})["monthly"][mk] = {
                "act_plan": num(g(r, 3)), "act_fact": num(g(r, 4)),
                "act_forecast": num(g(r, 5)), "portfolio": num(g(r, 6)),
                "deviation": num(g(r, 7)), "pct": num(g(r, 8)),
                "acts_count": num(g(r, 9)), "init_effect": num(g(r, 10)),
                "status": text(g(r, 11)),
            }

    # --- 4. Расходы и операционный финрезультат --- (A=month B..J)
    expenses = {}
    if 'expenses' in sec:
        a, b = sec['expenses']
        for r in range(a, b + 1):
            mk = month_key(g(r, 1))
            if not mk:
                continue
            expenses[mk] = {
                "admin_fot": num(g(r, 2)), "direct_fot": num(g(r, 3)),
                "commercial_fot": num(g(r, 4)), "direct_other": num(g(r, 5)),
                "allocated_oh": num(g(r, 6)), "expenses_total": num(g(r, 7)),
                "revenue": num(g(r, 8)), "finrez": num(g(r, 9)), "margin": num(g(r, 10)),
            }

    # --- 5. Недельные действия / инициативы --- (raw, факт может быть текстом!)
    actions = []
    if 'actions' in sec:
        a, b = sec['actions']
        for r in range(a, b + 1):
            mk = month_key(g(r, 1))
            manager, init_s = text(g(r, 2)), text(g(r, 3))
            executor, init_e = text(g(r, 6)), text(g(r, 7))
            if not any([manager, init_s, executor, init_e]):
                continue
            actions.append({
                "month": mk, "month_raw": text(g(r, 1)),
                "sales": {"manager": manager, "initiative": init_s,
                          "expected_contract": g(r, 4), "fact_contract": g(r, 5)} if (manager or init_s) else None,
                "execution": {"executor": executor, "initiative": init_e,
                              "expected_act": g(r, 8), "fact_act": g(r, 9)} if (executor or init_e) else None,
            })

    return {"monthly": monthly, "quarter": quarter, "managers": managers,
            "executors": executors, "expenses": expenses, "actions": actions}


# ---------------------------------------------------------------------------
# Tier 2: Договора (пореестровые сделки, горизонтальные блоки по месяцам)
# ---------------------------------------------------------------------------

def parse_deals(grid: dict) -> list:
    deals = []
    anchors = [(r, c) for (r, c), v in grid.items() if text(v) == 'Компания:']
    for (hr, c) in anchors:
        month = text(grid.get((hr - 1, c)))
        gap = 0
        rr = hr + 1
        while gap < 3 and rr < hr + 200:
            company = text(grid.get((rr, c)))
            if company:
                deals.append({
                    "month": month,
                    "company": company,
                    "sum_vat": num(grid.get((rr, c + 2))),
                    "sum_novat": num(grid.get((rr, c + 3))),
                    "manager": text(grid.get((rr, c + 4))),
                })
                gap = 0
            else:
                gap += 1
            rr += 1
    return deals


# ---------------------------------------------------------------------------
# Tier 2: КП и Звонки (две таблицы план/факт по менеджерам, помесячно)
# ---------------------------------------------------------------------------

def _parse_count_table(grid: dict, label_row: int, end_row: int) -> dict:
    """Менеджеры в строке label_row-1 (план=col, факт=col+1); месяцы в col A ниже.
    end_row ограничивает таблицу, чтобы КП не «затекали» в звонки и наоборот."""
    mgr_cols = {}
    for (r, c), v in list(grid.items()):
        if r == label_row - 1 and c >= 4:
            nm = text(v)
            if nm and nm.lower() not in _HEADER_WORDS and nm.lower() not in ('план', 'факт'):
                mgr_cols[nm] = c
    out = {}
    for rr in range(label_row + 1, end_row + 1):
        mk = month_key(grid.get((rr, 1)))
        if not mk:
            continue
        for nm, c in mgr_cols.items():
            plan = grid.get((rr, c))
            fact = grid.get((rr, c + 1))
            out.setdefault(nm, {})[mk] = {"plan": num(plan), "fact": num(fact)}
    return out


def parse_funnel(grid: dict) -> dict:
    kp_row = calls_row = None
    for (r, c), v in grid.items():
        if c == 1:
            s = str(v).lower()
            if 'кол-во кп' in s or 'количество кп' in s:
                kp_row = r
            elif 'звонк' in s and ('кол' in s or 'количество' in s):
                calls_row = r
    funnel = {}
    max_r = max((r for (r, _c) in grid), default=0)
    if kp_row:
        kp_end = (calls_row - 1) if (calls_row and calls_row > kp_row) else max_r
        funnel["kp"] = _parse_count_table(grid, kp_row, kp_end)
    if calls_row:
        calls_end = (kp_row - 1) if (kp_row and kp_row > calls_row) else max_r
        funnel["calls"] = _parse_count_table(grid, calls_row, calls_end)
    return funnel


# ---------------------------------------------------------------------------
# Главная
# ---------------------------------------------------------------------------

def find_main_sheet(sheets: dict) -> str:
    for name, grid in sheets.items():
        for (r, c), v in grid.items():
            if c == 1 and isinstance(v, str) and v.strip().startswith('1.') and 'свод' in v.lower():
                return name
    return next(iter(sheets))


def find_sheet_by_keyword(sheets: dict, *kws) -> str | None:
    for name in sheets:
        lo = name.lower()
        if any(k in lo for k in kws):
            return name
    return None


def extract(path: str) -> dict:
    sheets = load_sheets(path)
    warnings = []
    main_name = find_main_sheet(sheets)
    main = parse_main(sheets[main_name], warnings)

    deals_sheet = find_sheet_by_keyword(sheets, 'договор')
    funnel_sheet = find_sheet_by_keyword(sheets, 'кп', 'звонк')
    deals = parse_deals(sheets[deals_sheet]) if deals_sheet else []
    funnel = parse_funnel(sheets[funnel_sheet]) if funnel_sheet else {}

    return {
        "source_file": path,
        "sheets_found": list(sheets.keys()),
        "main_sheet": main_name,
        "tier": {
            "standard": True,
            "proof_deals": bool(deals),
            "proof_funnel": bool(funnel),
        },
        **main,
        "deals": deals,
        "funnel": funnel,
        "warnings": warnings,
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\User\Downloads\1. Юнит-экономика_ЭКОЛОГИЯ (01.06.-05.06).xlsx"
    data = extract(path)
    out = r"C:\Users\User\Claude\Projects\ai-findir-lab\extracted_v3.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("OK ->", out)
    print("sheets:", data["sheets_found"])
    print("tier:", data["tier"])
    print("managers(sales):", list(data["managers"].keys()))
    print("executors:", list(data["executors"].keys()))
    print("deals:", len(data["deals"]), "| funnel tables:", list(data["funnel"].keys()))
