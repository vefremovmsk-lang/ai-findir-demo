# -*- coding: utf-8 -*-
"""
radar — регуляторно-сезонный радар спроса (прототип).

Движок: событие регуляторики -> продукт из 00-слоя + сезонность + дата -> сигнал.
Лента событий: ЗАСЕЯНА из доменных знаний по РФ-экологии (стабильные дедлайны).
ВНИМАНИЕ: даты — seed, требуют сверки с живым источником (веб/MCP) при подключении.
Движок принимает любую ленту того же формата — это сменный вход.
"""
import datetime
from context_lib import parse_zero_layer

ZERO = r"C:\Users\User\Downloads\00 Про бизнес.xlsx"
OUT = r"C:\Users\User\Claude\Projects\ai-findir-lab\report_radar.txt"
TODAY = datetime.date(2026, 6, 8)

# ── ЗАСЕЯННАЯ ЛЕНТА (eco). deadlines = [(месяц, день), ...]; freq: annual|quarterly|ongoing ──
CALENDAR = [
    {"id": "nvos_plata_q", "title": "Плата за НВОС — квартальные авансы",
     "obligation": "Внести авансовый платёж за НВОС за квартал",
     "freq": "quarterly", "deadlines": [(4, 20), (7, 20), (10, 20)],
     "product_keywords": ["отчётн", "отчетн"], "lead_weeks": 4, "confidence": "high",
     "source": "ст.16.4 ФЗ-7; авансы до 20 числа след. за кварталом месяца"},
    {"id": "nvos_declar", "title": "Декларация о плате за НВОС (год)",
     "obligation": "Сдать годовую декларацию о плате за НВОС",
     "freq": "annual", "deadlines": [(3, 10)],
     "product_keywords": ["отчётн", "отчетн"], "lead_weeks": 4, "confidence": "high",
     "source": "до 10 марта за предыдущий год"},
    {"id": "2tp_othody", "title": "2-ТП (отходы)",
     "obligation": "Сдать статотчёт 2-ТП (отходы)",
     "freq": "annual", "deadlines": [(2, 1)],
     "product_keywords": ["отход", "отчётн", "отчетн"], "lead_weeks": 4, "confidence": "high",
     "source": "до 1 февраля"},
    {"id": "2tp_air_water", "title": "2-ТП (воздух/водхоз)",
     "obligation": "Сдать 2-ТП (воздух) и 2-ТП (водхоз)",
     "freq": "annual", "deadlines": [(1, 22)],
     "product_keywords": ["выброс", "сброс", "отчётн", "отчетн"], "lead_weeks": 4, "confidence": "high",
     "source": "до 22 января"},
    {"id": "pek_report", "title": "Отчёт по ПЭК",
     "obligation": "Сдать отчёт о производственном экологическом контроле",
     "freq": "annual", "deadlines": [(3, 25)],
     "product_keywords": ["пэк", "производствен"], "lead_weeks": 4, "confidence": "high",
     "source": "до 25 марта"},
    {"id": "ker", "title": "КЭР (объекты I категории)",
     "obligation": "Получить/актуализировать комплексное экологическое разрешение",
     "freq": "ongoing", "deadlines": [],
     "product_keywords": ["кэр"], "lead_weeks": 30, "confidence": "med",
     "source": "I категория; фаза основной обязанности — 2025, далее по мере категорирования"},
    {"id": "dvos", "title": "ДВОС (объекты II категории)",
     "obligation": "Подать/обновить декларацию о воздействии (раз в 7 лет или при изменениях)",
     "freq": "ongoing", "deadlines": [],
     "product_keywords": ["двос"], "lead_weeks": 8, "confidence": "med",
     "source": "II категория; обновление при изменении тех.процесса"},
    {"id": "ndv_inv", "title": "Инвентаризация выбросов / НДВ",
     "obligation": "Провести инвентаризацию источников и нормирование выбросов",
     "freq": "ongoing", "deadlines": [],
     "product_keywords": ["выброс", "атмосфер"], "lead_weeks": 10, "confidence": "med",
     "source": "периодически и при изменениях"},
    {"id": "waste_passport", "title": "Паспортизация отходов I–IV класса",
     "obligation": "Оформить/обновить паспорта отходов",
     "freq": "ongoing", "deadlines": [],
     "product_keywords": ["отход"], "lead_weeks": 4, "confidence": "med",
     "source": "при образовании/изменении отходов"},
    # ── события БЕЗ продукта в 00-слое → потенциальные пробелы ──
    {"id": "epr_util", "title": "РОП / утилизационный сбор (отчётность)",
     "obligation": "Отчитаться по нормативам утилизации и уплатить утильсбор",
     "freq": "annual", "deadlines": [(4, 15)],
     "product_keywords": ["роп", "утилизац", "утильсбор"], "lead_weeks": 4, "confidence": "med",
     "source": "реформа РОП 2024–2025; ежегодная отчётность производителей/импортёров"},
    {"id": "ghg_296", "title": "Углеродная отчётность (296-ФЗ)",
     "obligation": "Сдать годовой отчёт о выбросах парниковых газов (регулируемые лица)",
     "freq": "annual", "deadlines": [(7, 1)],
     "product_keywords": ["углерод", "парников", "климат", " esg"], "lead_weeks": 6, "confidence": "med",
     "source": "296-ФЗ; порог >150 тыс. т CO2-экв (далее >50 тыс.), до 1 июля"},
]


def next_deadline(deadlines):
    if not deadlines:
        return None
    cands = []
    for (mo, d) in deadlines:
        for yr in (TODAY.year, TODAY.year + 1):
            try:
                dt = datetime.date(yr, mo, d)
            except ValueError:
                continue
            if dt >= TODAY:
                cands.append(dt)
    return min(cands) if cands else None


def main():
    ctx = parse_zero_layer(ZERO)
    products = ctx["departments"].get("Экологические услуги", {}).get("products", [])
    pnames = [(p["name"], p["name"].lower(), p) for p in products]

    push_now, horizon, calendar_only, gaps = [], [], [], []
    for ev in CALENDAR:
        matched = [p for (nm, low, p) in pnames if any(k in low for k in ev["product_keywords"])]
        nd = next_deadline(ev["deadlines"])
        weeks = (nd - TODAY).days // 7 if nd else None
        rec = {"ev": ev, "deadline": nd, "weeks": weeks, "products": matched}
        if not matched:
            gaps.append(rec)
            continue
        if ev["freq"] == "ongoing":
            calendar_only.append(rec)
        elif weeks is None:
            calendar_only.append(rec)
        elif ev["lead_weeks"] <= weeks <= ev["lead_weeks"] + 5:
            push_now.append(rec)
        elif weeks < ev["lead_weeks"]:
            horizon.append(rec)  # дедлайн близко, но цикл не успеет — продавать на следующий
        elif weeks <= 18:
            horizon.append(rec)
        else:
            calendar_only.append(rec)

    L = []
    def p(s=""): L.append(str(s))

    def fmt_d(rec):
        d = rec["deadline"]
        return f"{d.strftime('%d.%m.%Y')} (через {rec['weeks']} нед.)" if d else "по факту категории"

    def season_ok(prod):
        return "Q2" in prod["season"]["quarters"]

    p("#" * 84)
    p(f"РЕГУЛЯТОРНО-СЕЗОННЫЙ РАДАР · Экология · на {TODAY.strftime('%d.%m.%Y')}")
    p("#" * 84)
    p("ВНИМАНИЕ: лента событий — seed из доменных знаний (живой веб сейчас недоступен).")
    p("Движок готов принять веб/MCP-фид того же формата. Даты сверить при подключении.")

    p("\n" + "=" * 84)
    p("🔴 ПРОДАВАТЬ СЕЙЧАС — дедлайн в окне, цикл успевает")
    p("=" * 84)
    if not push_now:
        p("  Нет событий в окне продаж.")
    for rec in sorted(push_now, key=lambda r: r["weeks"]):
        ev = rec["ev"]
        prods = ", ".join(pp["name"] for pp in rec["products"])
        conf = "✓ сезон подтверждает" if any(season_ok(pp) for pp in rec["products"]) else ""
        p(f"  • {ev['title']} — дедлайн {fmt_d(rec)}")
        p(f"      обязанность: {ev['obligation']}")
        p(f"      продаём: {prods}  (цикл ~{ev['lead_weeks']} нед.) {conf}")

    p("\n" + "=" * 84)
    p("🟡 НА ГОРИЗОНТЕ — готовить прогрев")
    p("=" * 84)
    for rec in sorted(horizon, key=lambda r: (r["weeks"] is None, r["weeks"])):
        ev = rec["ev"]
        p(f"  • {ev['title']} — {fmt_d(rec)} → {', '.join(pp['name'] for pp in rec['products'])}")

    p("\n" + "=" * 84)
    p("⚪ ПРОДУКТОВЫЕ ПРОБЕЛЫ — спрос есть, продукта в 00-слое НЕТ (кандидаты на запуск)")
    p("=" * 84)
    for rec in sorted(gaps, key=lambda r: (r["weeks"] is None, r["weeks"] if r["weeks"] is not None else 999)):
        ev = rec["ev"]
        hot = " 🔥 дедлайн близко!" if (rec["weeks"] is not None and rec["weeks"] <= 8) else ""
        p(f"  • {ev['title']} — {fmt_d(rec)}{hot}")
        p(f"      {ev['obligation']}")
        p(f"      источник: {ev['source']}")

    p("\n" + "=" * 84)
    p("📅 ПОСТОЯННЫЙ СПРОС / СПРАВОЧНО")
    p("=" * 84)
    for rec in calendar_only:
        ev = rec["ev"]
        p(f"  • {ev['title']} — {fmt_d(rec)} → {', '.join(pp['name'] for pp in rec['products']) or '—'}")

    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("radar ->", OUT)


if __name__ == "__main__":
    main()
