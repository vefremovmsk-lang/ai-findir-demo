# -*- coding: utf-8 -*-
"""
anonymize — обезличивание контракта отдела для ПУБЛИЧНОГО демо (GitHub).

Реальные данные компании наружу не идут. Демо сохраняет
ВСЮ механику продукта (графики, скоринг, вердикты, структуру), но убирает:
  • ФИО сотрудников  → вымышленные «Фамилия И.О.»; склонение сохраняется заменой
    ОСНОВЫ (Кириллов→Лебедев ⇒ Кирилловой→Лебедевой);
  • клиентов         → «Клиент N» (организации в кавычках / с орг-префиксом),
    одним проходом-регексом (без порчи перекрывающихся совпадений);
  • третьих лиц      → «Фамилия И.О.» в тексте → «контактное лицо»;
  • точные суммы     → ×коэффициент отдела (арифметика сохраняется).
Конкуренты (публичные участники рынка) и регуляторные дедлайны остаются.

Вход:  out/<slug>/analysis.json (реальный)
Выход: out/<slug>/analysis_demo.json → dash.render(slug, demo=True) → demo.html
"""
import os
import re
import json
import copy
from depts import OUT, DEPTS

# вымышленные ФИО по полу (для согласования падежных окончаний при замене основы)
FAKE_MASC = ["Алексеев А.В.", "Власов Д.И.", "Дроздов С.А.", "Жданов П.О.",
             "Кравцов А.Н.", "Миронов И.С.", "Орлов В.П.", "Зорин К.А.",
             "Соколов Р.М.", "Волков Г.Е.", "Семёнов А.Д.", "Голубев Н.В.",
             "Виноградов П.С.", "Богданов И.А.", "Фролов Д.К.", "Беляев С.Ю."]
FAKE_FEM = ["Борисова М.С.", "Громова Е.П.", "Ершова Н.К.", "Зуева Т.Л.",
            "Лебедева О.В.", "Панова И.Д.", "Серова А.В.", "Тихонова Е.М.",
            "Соколова Р.М.", "Волкова Г.Е.", "Семёнова А.Д.", "Голубева Н.В.",
            "Виноградова П.С.", "Богданова И.А.", "Фролова Д.К.", "Беляева С.Ю."]
FAKE_SURNAMES = {f.split()[0] for f in FAKE_MASC + FAKE_FEM}

FACTORS = {"eco": 0.84, "prod": 1.18, "uc": 0.92, "smk": 1.09}

# точечный денилист: имена без кавычек/префикса/инициалов, что регексы не ловят
EXTRA_REDACT = {
    "РТ-Техприемка": "«Заказчик А»", "Техприемка": "«Заказчик А»",
    "Справочник Эколога": "«отраслевой портал»", "Справочнику Эколога": "«отраслевому порталу»",
    "Справочника Эколога": "«отраслевого портала»", "Справочник": "«отраслевой портал»",
    "Экспортбаза": "«сервис лидогенерации»", "Экспортбазы": "«сервиса лидогенерации»",
    "Интеграл": "«обучающий центр»", "Интеграла": "«обучающего центра»", "Integral": "«обучающий центр»",
    "Паршиным": "«контактным лицом»", "Паршин": "«контактное лицо»",
    "ПримерКомпани": "«Компания»",
}
EXTRA_KEYS = sorted(EXTRA_REDACT, key=len, reverse=True)

# организации-клиенты. Объединённый регекс, ПЕРВЫМ — префиксная форма (длиннее,
# забирает целиком «АО "КТЦ "Электроника"» с вложенными кавычками), затем «…», затем "…".
P_PREFIX = (r'(?:ООО|ОАО|АО|ПАО|ЗАО|ГК|НПО|НПП|НПЦ|ФГУП|ФКП|АНО|ГКУ|ГБУ|МПО|ОАК|ИП|НАЗ|КАПО)\s+'
            r'["«]?[^,;:()\n]{2,60}')
P_ANGLE = r'«(?:[^«»]|«[^»]*»)*»'
P_ASCII = r'"[^"\n]{2,70}"'
CLIENT_RXES = (re.compile(P_PREFIX), re.compile(P_ANGLE), re.compile(P_ASCII))
COMBINED_CLIENT_RX = re.compile(f'(?:{P_PREFIX})|(?:{P_ANGLE})|(?:{P_ASCII})')

# «Фамилия И.О.» — третьи лица в свободном тексте
PERSON_INITIALS_RX = re.compile(r'[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ]\.\s?[А-ЯЁ]?\.?')
# суммы с разделителем тысяч пробелом: «2 681 535»
SPACED_RX = re.compile(r'\d{1,3}(?:[  ]\d{3})+')


def fmt_spaced(v):
    return f"{v:,}".replace(",", " ")


def is_year(v):
    return isinstance(v, int) and 2018 <= v <= 2035


def scale_num(v, f):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return v
    if abs(v) >= 1000 and not is_year(v):
        return round(v * f)
    return v


def scale_text_money(s, f):
    return SPACED_RX.sub(lambda mo: fmt_spaced(round(int(re.sub(r"[  ]", "", mo.group(0))) * f)), s)


def _stem(sur):
    """Основа фамилии. Срезаем только женское окончание -ова/-ева/-ина/-ына
    (Иванова→Иванов ⇒ Ивановой→Петровой). Несклоняемые на -о/-й
    (Шевченко, Бакши) и мужские -ов/-ев/-ин не трогаем — замена основы как
    подстроки и так покрывает их склонение (Соколов→Соколова→…)."""
    for suf in ("ова", "ева", "ина", "ына"):
        if sur.endswith(suf):
            return sur[:-1]
    return sur


def iter_strings(obj, skip=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == skip:
                continue
            yield from iter_strings(v, skip)
    elif isinstance(obj, list):
        for x in obj:
            yield from iter_strings(x, skip)
    elif isinstance(obj, str):
        yield obj


def build_name_map(A):
    """Карта ОСНОВ фамилий → фейк того же пола (по менеджерам контракта)."""
    surnames, seen = [], set()

    def add(n):
        sur = (n or "").split()[0] if (n or "").split() else ""
        if sur and sur not in seen and re.fullmatch(r"[А-ЯЁ][а-яё\-]{3,}", sur):
            seen.add(sur); surnames.append(sur)

    for key in ("calibration", "funnel"):
        for n in (A.get(key) or {}):
            add(n)
    for src in (A.get("commitments", []),
                (A.get("smart_control") or {}).get("rows", []),
                (A.get("ledger") or {}).get("rows", []),
                (A.get("waterfall") or {}).get("contract_bridge", {}).get("by_manager", [])):
        for r in src:
            add(r.get("manager"))
    for r in A.get("executors", []):     # исполнители/аудиторы — тоже реальные ФИО
        add(r.get("executor"))

    mi = fi = 0
    name_map = {}
    for sur in surnames:
        st = _stem(sur)
        if st in name_map:
            continue
        if sur[-1] in "ая":
            name_map[st] = _stem(FAKE_FEM[fi % len(FAKE_FEM)].split()[0]); fi += 1
        else:
            name_map[st] = _stem(FAKE_MASC[mi % len(FAKE_MASC)].split()[0]); mi += 1
    return name_map, sorted(name_map, key=len, reverse=True)


def apply_names(s, name_keys, name_map):
    for k in name_keys:
        if k in s:
            s = s.replace(k, name_map[k])
    return s


def redact_persons(s):
    def repl(mo):
        return mo.group(0) if mo.group(0).split()[0] in FAKE_SURNAMES else "«контактное лицо»"
    return PERSON_INITIALS_RX.sub(repl, s)


def make_client_sub(reg):
    """Замена клиентов одним проходом (без перекрытий) со сквозной нумерацией."""
    def repl(mo):
        t = re.sub(r"\s+", " ", mo.group(0).strip().strip('«»"').strip())
        if not t or t in reg["map"]:
            return f'«Клиент {reg["map"].get(t, "")}»' if t in reg["map"] else "«Клиент»"
        reg["n"] += 1
        reg["map"][t] = reg["n"]
        return f'«Клиент {reg["n"]}»'
    return repl


def fix_text(s, ctx):
    name_keys, name_map, reg, f = ctx
    if not isinstance(s, str):
        return s
    for k in EXTRA_KEYS:
        if k in s:
            s = s.replace(k, EXTRA_REDACT[k])
    s = COMBINED_CLIENT_RX.sub(make_client_sub(reg), s)   # клиенты — один проход
    s = apply_names(s, name_keys, name_map)               # основы фамилий
    s = redact_persons(s)                                  # третьи лица «Фамилия И.О.»
    s = scale_text_money(s, f)
    s = re.sub(r'»[»"“]+', '»', s)
    s = re.sub(r'["„«]+«', '«', s)
    return s.replace('«»', '').replace('  ', ' ').strip()


def transform(obj, ctx, in_competitors=False):
    name_keys, name_map, reg, f = ctx
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nk = apply_names(k, name_keys, name_map) if isinstance(k, str) else k
            out[nk] = transform(v, ctx, in_competitors or k == "competitors")
        return out
    if isinstance(obj, list):
        return [transform(x, ctx, in_competitors) for x in obj]
    if isinstance(obj, str):
        if in_competitors:   # рыночные соперники остаются; чистим лишь самоназвание+суммы
            s = obj
            for k in EXTRA_KEYS:
                if k in s:
                    s = s.replace(k, EXTRA_REDACT[k])
            return scale_text_money(s, f)
        return fix_text(obj, ctx)
    return scale_num(obj, f)


def anonymize(slug):
    A = json.load(open(os.path.join(OUT, slug, "analysis.json"), encoding="utf-8"))
    f = FACTORS.get(slug, 1.0)
    name_map, name_keys = build_name_map(A)
    reg = {"map": {}, "n": 0}
    ctx = (name_keys, name_map, reg, f)
    D = transform(copy.deepcopy(A), ctx)
    D["meta"]["demo"] = True
    D["meta"]["note"] = ("ДЕМО: данные обезличены (ФИО и клиенты вымышлены, суммы "
                         "масштабированы). Структура и механика — как в проде.")
    D["meta"]["department"] = D["meta"]["department"] + " · ДЕМО"
    out = os.path.join(OUT, slug, "analysis_demo.json")
    json.dump(D, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return out, len(name_map), reg["n"], f


if __name__ == "__main__":
    import sys
    for s in (sys.argv[1:] or list(DEPTS)):
        out, nn, nc, fac = anonymize(s)
        print(f"[{s}] -> {out} | основ ФИО: {nn} | клиентов: {nc} | масштаб ×{fac}")
