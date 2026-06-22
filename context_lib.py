# -*- coding: utf-8 -*-
"""context_lib — чистые функции 00-слоя (без побочных эффектов), для импорта."""
import re
from extract_v3 import load_sheets


def _t(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_money_range(s):
    if s is None:
        return None
    toks = re.findall(r"\d[\d\s ]*", str(s))
    vals = [int(re.sub(r"[\s ]", "", t)) for t in toks if re.sub(r"[\s ]", "", t)]
    vals = [v for v in vals if v >= 1000]
    if not vals:
        return None
    low, high = min(vals), max(vals)
    return {"low": low, "high": high, "mid": (low + high) // 2,
            "recurring": "мес" in str(s).lower(), "raw": str(s)}


_SEASON_TOKENS = [
    ("январ", "Q1"), ("феврал", "Q1"), ("март", "Q1"), ("i кв", "Q1"), ("начало года", "Q1"),
    ("апрел", "Q2"), ("май", "Q2"), ("мае", "Q2"), ("июн", "Q2"), ("ii кв", "Q2"), ("весн", "Q2"),
    ("июл", "Q3"), ("август", "Q3"), ("сентябр", "Q3"), ("iii кв", "Q3"), ("лет", "Q3"),
    ("октябр", "Q4"), ("ноябр", "Q4"), ("декабр", "Q4"), ("iv кв", "Q4"), ("осен", "Q4"),
]


def parse_season(s):
    if s is None:
        return {"strength": None, "quarters": [], "raw": None}
    lo = str(s).lower()
    if "нет" in lo or "не выражен" in lo:
        strength = "нет"
    elif "сильн" in lo:
        strength = "сильная"
    elif "слаб" in lo:
        strength = "слабая"
    else:
        strength = "есть"
    q = sorted({qq for tok, qq in _SEASON_TOKENS if tok in lo})
    return {"strength": strength, "quarters": q, "raw": str(s)}


def parse_zero_layer(path):
    sheets = load_sheets(path)
    ctx = {"company": {}, "departments": {}}
    info = sheets.get("Общая информация", {})
    maxr = max((r for r, c in info), default=0)
    for r in range(1, maxr + 1):
        k, v = _t(info.get((r, 1))), _t(info.get((r, 2)))
        if k:
            ctx["company"][k] = v
    for name, grid in sheets.items():
        if name == "Общая информация":
            continue
        maxr = max((r for r, c in grid), default=0)
        hdr = None
        for r in range(1, maxr + 1):
            if _t(grid.get((r, 2))) in ("Услуга", "Направление"):
                hdr = r
                break
        if hdr is None:
            continue
        products = []
        for r in range(hdr + 1, maxr + 1):
            pname = _t(grid.get((r, 2)))
            if not pname:
                continue
            products.append({
                "name": pname, "avg_check": parse_money_range(grid.get((r, 3))),
                "cycle": _t(grid.get((r, 4))), "repeat": _t(grid.get((r, 5))),
                "season": parse_season(grid.get((r, 6))), "lpr": _t(grid.get((r, 7))),
                "competitors": _t(grid.get((r, 8))), "complexity": grid.get((r, 9)),
            })
        ctx["departments"][name] = {"label": _t(grid.get((1, 2))) or name, "products": products}
    return ctx


def product_keywords(pname):
    lo = pname.lower()
    kws = set()
    for w in re.findall(r"[а-яёa-z]+", lo):
        if len(w) >= 4 and w not in ("услуг", "продукц", "соответств", "требован", "систем"):
            kws.add(w[:6])
    if "лаборатор" in lo:
        kws.add("лаб")
    if "аудит" in lo:
        kws.add("аудит")
    if "отчётн" in lo or "отчетн" in lo:
        kws |= {"отчет", "нвос"}
    return kws


def match_product(initiative, products):
    if not initiative:
        return None
    lo = initiative.lower()
    for p in products:
        for kw in product_keywords(p["name"]):
            if kw in lo:
                return p
    return None
