# -*- coding: utf-8 -*-
"""
owner — сводный дашборд СОБСТВЕННИКУ по всему портфелю отделов.

Агрегирует 4 контракта out/<slug>/analysis.json (или *_demo.json) в один экран:
портфельный финрез → рейтинг отделов → кому верить → что оспорить → что пушить →
конвейер собственнику. Рендерер НИЧЕГО не пересчитывает по сырью — только суммирует
готовые числа контрактов (как и принцип findir-dashboard: один источник).

  render(demo=False) -> (path, size, n_charts, n_sections)

real: out/owner.html      (фактические ФИО/клиенты — наружу не идёт)
demo: out/owner_demo.html (из *_demo.json — обезличено, безопасно публиковать)
"""
import os
import json

from depts import DEPTS, ORDER, OUT, CONTROL_DATE, PERIOD
from theme_findir import (CSS, INK, MUT, CRIMSON, AMBER, GREEN, INDIGO, SLATE,
                          money, short, pct, esc, surname, ech_init)

LAB = os.path.dirname(os.path.abspath(__file__))
ECHARTS_JS = open(os.path.join(LAB, "vendor", "echarts.min.js"), encoding="utf-8").read()

# вердикты обещаний, которые собственнику стоит оспорить (воронка не вытягивает)
CHALLENGE_VERDICTS = {"фантазия", "не сбылось"}
# метки надёжности, которым нельзя верить напрямую
WEAK_RELIABILITY = {"хронически завышает", "склонен завышать"}


def load(demo):
    fn = "analysis_demo.json" if demo else "analysis.json"
    data = {}
    for slug in ORDER:
        p = os.path.join(OUT, slug, fn)
        if os.path.exists(p):
            data[slug] = json.load(open(p, encoding="utf-8"))
    return data


def nz(v):
    return v if isinstance(v, (int, float)) else 0


def render(demo=False):
    data = load(demo)
    company = next((data[s]["meta"].get("company") for s in ORDER if s in data and data[s].get("meta")), "компании")
    if not data:
        raise RuntimeError("нет контрактов отделов — сначала прогон по отделам (run_all)")

    # ---- портфельные агрегаты (только суммы готовых чисел) ----
    agg = {k: 0 for k in ("finrez", "revenue_acts", "expenses", "deficit_to_zero",
                          "contract_plan", "contract_fact", "act_plan", "act_forecast")}
    rows = []
    for slug in ORDER:
        if slug not in data:
            continue
        dg = data[slug]["diagnosis"]
        for k in agg:
            agg[k] += nz(dg.get(k))
        rows.append((slug, dg))
    rows.sort(key=lambda r: nz(r[1].get("finrez")))           # худший финрез сверху
    port_contract_pct = (agg["contract_fact"] / agg["contract_plan"]) if agg["contract_plan"] else None

    # ---- алерты портфеля (critical → warn) ----
    crit, warn = [], []
    for slug in ORDER:
        if slug not in data:
            continue
        for a in data[slug].get("alerts", []):
            tgt = crit if a.get("level") == "critical" else (warn if a.get("level") == "warn" else None)
            if tgt is not None:
                tgt.append((slug, a))

    # ---- кому верить: руководители, чьим прогнозам нельзя верить напрямую ----
    weak = []
    for slug in ORDER:
        if slug not in data:
            continue
        for mgr, d in data[slug].get("calibration", {}).items():
            if d.get("reliability") in WEAK_RELIABILITY:
                weak.append((slug, mgr, d))
    weak.sort(key=lambda x: (x[2].get("forecast_realism") if x[2].get("forecast_realism") is not None else 1))

    # ---- что оспорить: обещания, которые воронка/история не вытягивает ----
    challenge = []
    unverif = {slug: 0 for slug in ORDER}
    for slug in ORDER:
        if slug not in data:
            continue
        for c in data[slug].get("commitments", []):
            if c.get("verdict") == "не проверяемо" and not c.get("closed"):
                unverif[slug] += 1
            if c.get("verdict") in CHALLENGE_VERDICTS and nz(c.get("expected")) > 0:
                challenge.append((slug, c))
    challenge.sort(key=lambda x: -nz(x[1].get("expected")))

    # ---- что пушить: регуляторный радар + сезонные сильные ----
    push = []
    for slug in ORDER:
        if slug not in data:
            continue
        rad = data[slug].get("radar") or {}
        for r in rad.get("push_now", []):
            push.append((slug, "радар", r.get("title"), r.get("deadline"), r.get("weeks"),
                         ", ".join(r.get("products", []))))
        seas = data[slug].get("seasonality") or {}
        for s in seas.get("q2_push", []):
            if s.get("strength") == "сильная":
                push.append((slug, "сезон", s.get("name"), None, None,
                             f'цикл {s.get("cycle","—")} · чек {money(s.get("avg_check"))}'))

    # ---- конвейер собственнику: топ-действий по отделам ----
    pipe = []
    for slug in ORDER:
        if slug not in data:
            continue
        for a in (data[slug].get("action_pipeline", []) or [])[:2]:
            pipe.append((slug, a))

    # ================= РЕНДЕР =================
    def dep_chip(slug):
        return f'<span class="chip">{esc(DEPTS[slug]["title"])}</span>'

    badge = ' · ДЕМО' if demo else ''
    demo_badge = ('<span style="background:#fff3f4;color:#d12b3b;border:1px solid #f3c9cd;'
                  'border-radius:6px;padding:2px 8px;font-size:11px;margin-left:8px">ДЕМО</span>') if demo else ''

    # — герой-график: финрез по отделам (всё в минусе → crimson) —
    cat = [DEPTS[s]["title"] for s, _ in rows]
    vals = [round(nz(dg.get("finrez")) / 1e6, 3) for _, dg in rows]
    chart_div, chart_js = ech_init("finrez_by_dept", {
        "grid": {"left": 8, "right": 18, "top": 16, "bottom": 8, "containLabel": True},
        "tooltip": {"trigger": "axis", "valueFormatter": "VF"},
        "xAxis": {"type": "value", "axisLabel": {"formatter": "{value} млн"},
                  "splitLine": {"lineStyle": {"color": "#eee"}}},
        "yAxis": {"type": "category", "data": cat, "inverse": True},
        "series": [{"type": "bar", "data": vals, "itemStyle": {"color": CRIMSON},
                    "label": {"show": True, "position": "right",
                              "formatter": "{c} млн", "fontFamily": "Cascadia Mono, Consolas, monospace"}}],
    }, height=210)
    # valueFormatter не сериализуется как функция — заменим плейсхолдер на JS-функцию
    chart_js = chart_js.replace('"VF"', "function(v){return v+' млн ₽';}")

    # — алерты —
    def alert_html():
        if not crit and not warn:
            return ""
        items = ""
        for slug, a in crit:
            items += (f'<div class="al crit"><span class="alt">{dep_chip(slug)} {esc(a.get("tag"))}</span>'
                      f'<span class="alx">{esc(a.get("text"))}</span></div>')
        for slug, a in warn[:6]:
            items += (f'<div class="al warn"><span class="alt">{dep_chip(slug)} {esc(a.get("tag"))}</span>'
                      f'<span class="alx">{esc(a.get("text"))}</span></div>')
        more = f'<div class="muted" style="margin-top:6px">…и ещё {len(warn)-6} предупреждений</div>' if len(warn) > 6 else ""
        return (f'<div class="sec" id="alerts"><div class="eyebrow">Где горит — по портфелю</div>'
                f'<h2>Критичное и предупреждения всех отделов</h2>{items}{more}</div>')

    # — рейтинг отделов —
    rank_rows = ""
    for slug, dg in rows:
        fr = nz(dg.get("finrez"))
        cp = dg.get("contract_pct")
        rank_rows += (
            f'<tr><td class="dep">{esc(DEPTS[slug]["name"])}</td>'
            f'<td class="num crim">{money(fr)}</td>'
            f'<td class="num">{pct(cp)}</td>'
            f'<td class="num">{money(nz(dg.get("deficit_to_zero")))}</td>'
            f'<td class="num">{short(nz(dg.get("revenue_acts"))).lstrip("+")}</td>'
            f'<td class="num">{short(nz(dg.get("expenses"))).lstrip("+")}</td>'
            f'<td><a href="{slug}/{"demo.html" if demo else "dashboard.html"}">открыть →</a></td></tr>')
    rank = (f'<div class="sec" id="rank"><div class="eyebrow">Рейтинг отделов</div>'
            f'<h2>Кто сколько недодал — от худшего к лучшему</h2>'
            f'<table class="tbl"><thead><tr><th>Отдел</th><th class="num">Финрез Q2</th>'
            f'<th class="num">Контракт.</th><th class="num">До нуля</th><th class="num">Акты</th>'
            f'<th class="num">Расходы</th><th></th></tr></thead><tbody>{rank_rows}</tbody></table></div>')

    # — кому верить —
    if weak:
        wr = ""
        for slug, mgr, d in weak:
            wr += (f'<tr><td>{dep_chip(slug)} <b>{esc(mgr)}</b></td>'
                   f'<td class="num">{pct(d.get("attainment"))}</td>'
                   f'<td class="num crim">{pct(d.get("forecast_realism"))}</td>'
                   f'<td>{esc(d.get("reliability"))}</td>'
                   f'<td class="num">{money(nz(d.get("forecast")))}</td></tr>')
        trust = (f'<div class="sec" id="trust"><div class="eyebrow">Кому верить</div>'
                 f'<h2>Чьим прогнозам нельзя верить напрямую — дисконтируй в своде</h2>'
                 f'<table class="tbl"><thead><tr><th>Руководитель</th><th class="num">Вып. плана</th>'
                 f'<th class="num">Сбыв. прогноза</th><th>Вердикт</th><th class="num">Прогноз сейчас</th>'
                 f'</tr></thead><tbody>{wr}</tbody></table>'
                 f'<div class="muted">«Сбыв. прогноза» — доля прошлых обещаний, ставших фактом. '
                 f'Низкая → прогноз руководителя в своде режь.</div></div>')
    else:
        trust = ""

    # — что оспорить —
    if challenge:
        ch = ""
        for slug, c in challenge[:8]:
            ch += (f'<tr><td>{dep_chip(slug)} {esc(c.get("manager"))}</td>'
                   f'<td>{esc(c.get("initiative"))}</td>'
                   f'<td class="num crim">{money(nz(c.get("expected")))}</td>'
                   f'<td class="num">{("нужно ~"+str(c.get("kp_need"))+" КП") if c.get("kp_need") else "—"}</td>'
                   f'<td>{esc(c.get("verdict"))}</td></tr>')
        unv = " · ".join(f'{DEPTS[s]["title"]}: {n}' for s, n in unverif.items() if n)
        unv_line = f'<div class="muted">Непроверяемых обещаний (нет воронки на стол): {unv}</div>' if unv else ""
        challenge_sec = (f'<div class="sec" id="challenge"><div class="eyebrow">Что оспорить на разборе</div>'
                         f'<h2>Обещания, которые воронка/история не вытягивает</h2>'
                         f'<table class="tbl"><thead><tr><th>Менеджер</th><th>Инициатива</th>'
                         f'<th class="num">Обещано</th><th class="num">Воронка</th><th>Вердикт</th>'
                         f'</tr></thead><tbody>{ch}</tbody></table>{unv_line}</div>')
    else:
        challenge_sec = ""

    # — что пушить —
    if push:
        pr = ""
        for slug, kind, title, deadline, weeks, note in push[:10]:
            dl = ""
            if deadline:
                dl = f'{deadline}' + (f' · через {weeks} нед' if weeks else '')
            pr += (f'<tr><td>{dep_chip(slug)}<span class="kind">{esc(kind)}</span></td>'
                   f'<td><b>{esc(title)}</b></td><td>{esc(note)}</td>'
                   f'<td class="num">{esc(dl) if dl else "—"}</td></tr>')
        push_sec = (f'<div class="sec" id="push"><div class="eyebrow">Что пушить сейчас</div>'
                    f'<h2>Окна спроса: регуляторика и сезонность</h2>'
                    f'<table class="tbl"><thead><tr><th>Источник</th><th>Продукт / повод</th>'
                    f'<th>Параметры</th><th class="num">Дедлайн</th></tr></thead>'
                    f'<tbody>{pr}</tbody></table></div>')
    else:
        push_sec = ""

    # — конвейер собственнику —
    pp = ""
    for slug, a in pipe:
        pp += (f'<tr><td>{dep_chip(slug)}</td><td><b>{esc(a.get("action"))}</b>'
               f'<div class="muted">{esc(a.get("basis",""))}</div></td>'
               f'<td>{esc(a.get("owner",""))}</td><td class="dl">{esc(a.get("deadline",""))}</td>'
               f'<td>{esc(a.get("effect",""))}</td></tr>')
    pipe_sec = (f'<div class="sec" id="pipe"><div class="eyebrow">Конвейер действий — собственнику</div>'
                f'<h2>Что взять под личный контроль на неделю</h2>'
                f'<table class="tbl"><thead><tr><th>Отдел</th><th>Действие · основание</th>'
                f'<th>Ответственный</th><th>Срок</th><th>Эффект</th></tr></thead>'
                f'<tbody>{pp}</tbody></table></div>')

    nav = ('<a href="#alerts">Где горит</a><a href="#rank">Рейтинг</a>'
           '<a href="#trust">Кому верить</a><a href="#challenge">Оспорить</a>'
           '<a href="#push">Пушить</a><a href="#pipe">Конвейер</a>')

    n_sections = sum(bool(x) for x in [alert_html(), True, trust, challenge_sec, push_sec, True])

    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI-Findir · Свод собственнику Q2 2026{badge}</title>
<style>{CSS}
.owner-extra{{}}
.chip{{display:inline-block;background:#eef0fb;color:{INDIGO};border:1px solid #dfe3f7;
  border-radius:6px;padding:1px 7px;font-size:11px;font-family:var(--mono);margin-right:4px}}
.kind{{display:inline-block;background:#f4f4f2;color:{MUT};border-radius:5px;padding:1px 6px;
  font-size:10.5px;font-family:var(--mono);margin-left:5px}}
.tbl{{width:100%;border-collapse:collapse;margin-top:8px;font-size:13.5px}}
.tbl th{{text-align:left;font-family:var(--mono);font-size:11px;color:{MUT};font-weight:600;
  text-transform:uppercase;letter-spacing:.03em;border-bottom:1.5px solid var(--line);padding:7px 9px}}
.tbl td{{padding:8px 9px;border-bottom:1px solid var(--line);vertical-align:top}}
.tbl td.num{{font-family:var(--mono);text-align:right;white-space:nowrap}}
.tbl td.dep{{font-weight:600}}
.tbl td.crim,.tbl td .crim{{color:{CRIMSON}}}
.tbl .dl{{font-family:var(--mono);white-space:nowrap}}
.tbl .muted{{font-size:11.5px;color:{MUT};margin-top:2px}}
.muted{{font-size:12px;color:{MUT};margin-top:8px}}
.al{{display:flex;gap:12px;padding:9px 12px;border-radius:9px;margin:6px 0;align-items:baseline}}
.al.crit{{background:#fff3f4;border:1px solid #f3c9cd}}
.al.warn{{background:#fff9ef;border:1px solid #f0e0bf}}
.al .alt{{font-family:var(--mono);font-size:11.5px;white-space:nowrap;font-weight:600}}
.al.crit .alt{{color:{CRIMSON}}} .al.warn .alt{{color:{AMBER}}}
.al .alx{{font-size:13px}}
.pgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}}
.pcard{{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:12px 14px}}
.pcard .l{{font-family:var(--mono);font-size:10.5px;color:{MUT};text-transform:uppercase;letter-spacing:.03em}}
.pcard .v{{font-family:var(--mono);font-size:18px;font-weight:700;margin-top:3px}}
</style></head><body><div class="wrap">

<div class="top">
  <div><div class="brand">AI-<b>Findir</b> · свод собственнику{demo_badge}</div>
  <div class="h1">Портфель отделов — {esc(company)} · {PERIOD}</div></div>
  <div class="top-meta">контроль: {CONTROL_DATE}<br>отделов: {len(rows)}<br>факт: апрель, май · прогноз: июнь</div>
</div>
<nav class="nav">{nav}</nav>

{alert_html()}

<div class="hero2" id="hero">
  <div class="left">
    <div class="lbl">Операционный финрез портфеля Q2</div>
    <div class="big">{money(agg["finrez"])}</div>
    <div class="sub">Сумма по {len(rows)} отделам. До нуля портфелю не хватает выручки {money(agg["deficit_to_zero"])}.
      Контрактация портфеля {pct(port_contract_pct)} плана.</div>
    <div class="kpis">
      <div class="k"><div class="v">{short(agg["revenue_acts"]).lstrip("+")}</div><div class="l">акты</div></div>
      <div class="k"><div class="v">{short(agg["expenses"]).lstrip("+")}</div><div class="l">расходы</div></div>
      <div class="k"><div class="v" style="color:{CRIMSON}">{short(agg["deficit_to_zero"]).lstrip("+")}</div><div class="l">до нуля</div></div>
    </div>
  </div>
  <div class="right"><div class="cap">финрез по отделам (всё в минусе — где глубже)</div>{chart_div}</div>
</div>

{rank}
{trust}
{challenge_sec}
{push_sec}
{pipe_sec}

<div class="foot">
  <div>Источник: out/&lt;отдел&gt;/analysis{'_demo' if demo else ''}.json · суммы без пересчёта сырья{' · ДЕМО (обезличено)' if demo else ''}</div>
  <div>AI-Findir · Свод собственнику · ECharts офлайн</div>
</div>

</div>
<script>{ECHARTS_JS}</script>
<script>
{chart_js}
window.addEventListener('resize',function(){{document.querySelectorAll('.chart').forEach(function(el){{var c=echarts.getInstanceByDom(el);if(c)c.resize();}});}});
</script>
</body></html>"""

    out = os.path.join(OUT, "owner_demo.html" if demo else "owner.html")
    open(out, "w", encoding="utf-8").write(html)
    return out, len(html), 1, n_sections


if __name__ == "__main__":
    for d in (False, True):
        p, sz, ch, sec = render(demo=d)
        print(("demo " if d else "real "), p, f"{sz/1e6:.2f}МБ", f"{sec} секц")
