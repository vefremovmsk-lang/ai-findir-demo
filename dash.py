# -*- coding: utf-8 -*-
"""
dash — обобщённый генератор дашборда AI-Findir (Дашборд 2.0) из контракта отдела.

Читает out/<slug>/analysis.json, рендерит фирменный дашборд (theme_findir +
ECharts офлайн). Универсален: навигация и секции адаптируются к тому, что есть
в контракте. Две оси обещаний:
  • grounding (есть воронка, экология): «что воронка не вытянет» (нужно/есть КП)
  • fact (нет воронки, прод/УЦ): «обещано → факт» (что сбылось / не сбылось)

Пишет out/<slug>/dashboard.html (standalone, двойным кликом).
"""
import os
import sys
import json
from theme_findir import (CSS, CRIMSON, AMBER, GREEN, INDIGO, SLATE, LINE,
                          money, short, pct, esc, surname, ech_init)
from depts import LAB, OUT

ECHARTS_JS = open(os.path.join(LAB, "vendor", "echarts.min.js"), encoding="utf-8").read()


def render(slug, demo=False):
    src = os.path.join(OUT, slug, "analysis.json" if not demo else "analysis_demo.json")
    A = json.load(open(src, encoding="utf-8"))
    dg = A["diagnosis"]
    title = A["meta"]["title"]
    dept = A["meta"]["department"]
    charts_js = []
    sections = []   # (id, nav_label, hot, html)

    # ---------- ГЕРОЙ: водопад финреза ----------
    wf = A.get("waterfall", {})
    fb = wf.get("finrez_bridge")
    wf_div = ""
    if fb:
        bars, cum = [], 0.0
        bars.append({"label": "при плановых актах", "y0": 0, "y1": fb["start"]["value"], "kind": "st"})
        cum = fb["start"]["value"]
        for s in fb["steps"]:
            bars.append({"label": s["label"], "y0": cum, "y1": cum + s["delta"],
                         "kind": "neg" if s["delta"] < 0 else "pos"})
            cum += s["delta"]
        bars.append({"label": "финрез факт", "y0": 0, "y1": fb["end"]["value"], "kind": "en"})
        data = [[i, b["y0"], b["y1"], b["kind"], b["label"]] for i, b in enumerate(bars)]
        cats = [b["label"].replace(" ", "\n", 1) for b in bars]
        wf_div = '<div id="wf" class="chart" style="height:300px"></div>'
        charts_js.append("""
(function(){
  var COLORS={st:'%(indigo)s',en:'%(slate)s',neg:'%(crimson)s',pos:'%(green)s'};
  var data=%(data)s, cats=%(cats)s;
  echarts.init(document.getElementById('wf')).setOption({
    animationDuration:700,
    grid:{left:70,right:16,top:28,bottom:44},
    xAxis:{type:'category',data:cats,axisTick:{show:false},axisLine:{lineStyle:{color:'%(line)s'}},
      axisLabel:{fontSize:10,color:'%(slate)s',interval:0,lineHeight:13}},
    yAxis:{type:'value',axisLabel:{formatter:function(v){return (v/1e6).toFixed(1)+'М';},fontSize:10},
      splitLine:{lineStyle:{color:'#f0efeb'}}},
    tooltip:{trigger:'item',formatter:function(p){
      var d=p.data;var delta=d[2]-d[1];var f=function(x){return x.toLocaleString('ru-RU')+' \\u20bd';};
      if(d[3]==='st'||d[3]==='en') return '<b>'+d[4]+'</b><br>'+f(d[2]);
      return '<b>'+d[4]+'</b><br>'+(delta>0?'+':'')+f(delta);}},
    series:[{type:'custom',
      renderItem:function(params,api){
        var i=api.value(0),y0=api.value(1),y1=api.value(2);
        var kind=data[i][3];
        var p0=api.coord([i,y0]),p1=api.coord([i,y1]);
        var w=api.size([1,0])[0]*0.55;
        var top=Math.min(p0[1],p1[1]),h=Math.max(3,Math.abs(p0[1]-p1[1]));
        var children=[{type:'rect',shape:{x:p0[0]-w/2,y:top,width:w,height:h,r:4},
          style:{fill:COLORS[kind]}}];
        if(i<data.length-1){
          var pn=api.coord([i+1,y1]);
          children.push({type:'line',shape:{x1:p0[0]+w/2,y1:p1[1],x2:pn[0]-w/2,y2:p1[1]},
            style:{stroke:'#c9c8c2',lineDash:[4,3],lineWidth:1}});
        }
        return {type:'group',children:children};
      },
      encode:{x:0,y:[1,2]},data:data,
      label:{show:true,position:'top',fontSize:10.5,fontFamily:'Cascadia Mono,Consolas,monospace',
        formatter:function(p){var d=p.data;var v=(d[3]==='st'||d[3]==='en')?d[2]:(d[2]-d[1]);
          var s=Math.abs(v)>=1e6?(v/1e6).toFixed(2)+' млн':(v/1e3).toFixed(0)+' тыс';
          return (v>0&&d[3]!=='st'&&d[3]!=='en'?'+':'')+s;}}
    }]
  });
})();""" % {"indigo": INDIGO, "slate": SLATE, "crimson": CRIMSON, "green": GREEN,
             "line": LINE, "data": json.dumps(data, ensure_ascii=False),
             "cats": json.dumps(cats, ensure_ascii=False)})

    # ---------- алерты / срочное ----------
    alert_html = "".join(f'<div class="alert {a["level"]}"><span class="atag">{esc(a["tag"])}</span>'
                         f'<div>{esc(a["text"])}</div></div>' for a in A.get("alerts", []))
    if alert_html:
        sections.append(("alerts", "алерты", True,
                         f'<div class="eyebrow">Критичные алерты</div><div class="alertband">{alert_html}</div>'))

    urgent_html = "".join(f'<div class="uitem"><span class="n">{i+1}</span><div>{esc(x)}</div></div>'
                          for i, x in enumerate(A.get("head_urgent", [])))
    if urgent_html:
        sections.append(("urgent", "срочно", False,
                         f'<div class="urgent"><h3>⚡ Срочно — руководителю отдела</h3>{urgent_html}</div>'))

    # ---------- мост контрактации по менеджерам ----------
    cb = wf.get("contract_bridge")
    if cb and cb.get("by_manager"):
        rows = cb["by_manager"]
        names = [surname(r["manager"]) for r in rows][::-1]
        plans = [r["plan"] for r in rows][::-1]
        facts = [r["fact"] for r in rows][::-1]
        div, js = ech_init("cbridge", {
            "grid": {"left": 90, "right": 96, "top": 10, "bottom": 24},
            "xAxis": {"type": "value", "axisLabel": {"show": False}, "splitLine": {"show": False}},
            "yAxis": {"type": "category", "data": names,
                      "axisLabel": {"fontSize": 12, "fontWeight": 600, "color": SLATE},
                      "axisTick": {"show": False}, "axisLine": {"show": False}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "series": [
                {"name": "план", "type": "bar", "data": plans, "barGap": "-100%",
                 "barWidth": 16, "itemStyle": {"color": "#e9e8e3", "borderRadius": 4}, "z": 1},
                {"name": "факт", "type": "bar", "data": facts, "barWidth": 8,
                 "itemStyle": {"color": INDIGO, "borderRadius": 3}, "z": 2,
                 "label": {"show": True, "position": "right", "fontSize": 10.5,
                           "fontFamily": "Cascadia Mono,Consolas,monospace", "formatter": "{c}"}},
            ],
        }, height=46 * len(rows) + 50)
        charts_js.append(js)
        cb_html = (f'<div style="font-size:12.5px;color:var(--mut);margin-bottom:4px">План '
                   f'{money(cb["plan"])} → факт {money(cb["fact"])} '
                   f'(<b style="color:{CRIMSON}">{short(cb["delta"])}</b>). Серая полоса — план, цветная — факт.</div>' + div)
        sections.append(("most", "контрактация", False,
                         f'<div class="eyebrow">Контрактация</div><h2>Кто недодал план — мост по менеджерам</h2>'
                         f'<div class="card">{cb_html}</div>'))

    # ---------- калибровка ----------
    cal = A.get("calibration", {})
    cal_rows = [(surname(n), c) for n, c in cal.items() if c.get("forecast_realism") is not None]
    if cal_rows:
        cal_rows.sort(key=lambda x: x[1]["forecast_realism"])
        names = [n for n, _ in cal_rows]
        realism = [round(c["forecast_realism"] * 100) for _, c in cal_rows]
        attain = [round((c["attainment"] or 0) * 100) for _, c in cal_rows]
        colors = [CRIMSON if r < 35 else (AMBER if r < 60 else GREEN) for r in realism]
        div, js = ech_init("calib", {
            "grid": {"left": 90, "right": 60, "top": 30, "bottom": 24},
            "legend": {"data": ["сбываемость прогноза", "выполнение плана"], "top": 0, "textStyle": {"fontSize": 11}},
            "xAxis": {"type": "value", "max": 160, "axisLabel": {"formatter": "{value}%", "fontSize": 10},
                      "splitLine": {"lineStyle": {"color": "#f0efeb"}}},
            "yAxis": {"type": "category", "data": names,
                      "axisLabel": {"fontSize": 12, "fontWeight": 600, "color": SLATE},
                      "axisTick": {"show": False}, "axisLine": {"show": False}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "series": [
                {"name": "сбываемость прогноза", "type": "bar", "barWidth": 14,
                 "data": [{"value": v, "itemStyle": {"color": c, "borderRadius": 4}} for v, c in zip(realism, colors)],
                 "label": {"show": True, "position": "right", "formatter": "{c}%", "fontSize": 10.5,
                           "fontFamily": "Cascadia Mono,Consolas,monospace"}},
                {"name": "выполнение плана", "type": "scatter", "symbol": "diamond", "symbolSize": 13,
                 "data": attain, "itemStyle": {"color": SLATE}},
            ],
        }, height=44 * len(names) + 60)
        charts_js.append(js)
        cal_table = ""
        for n, c in sorted(cal.items(), key=lambda kv: (kv[1]["forecast_realism"] is None, kv[1]["forecast_realism"] or 0)):
            r = c.get("forecast_realism")
            if r is None:
                continue
            cls = "r" if r < 0.35 else ("a" if r < 0.6 else "g")
            cal_table += (f'<tr><td><b>{surname(n)}</b></td><td class="num">{pct(c["attainment"])}</td>'
                          f'<td class="num">{pct(r)}</td><td><span class="pill {cls}">{esc(c.get("reliability"))}</span></td></tr>')
        sections.append(("trust", "кому верить", False,
                         f'<div class="eyebrow">Кому верить</div><h2>Достоверность руководителей</h2>'
                         f'<div class="lead">Полоса — сбываемость прогноза (факт/прогноз). Ромб — выполнение плана. '
                         f'Красное — прогнозу верить нельзя.</div><div class="card">{div}</div>'
                         f'<table style="margin-top:14px"><tr><th>Менеджер</th><th style="text-align:right">Вып. плана</th>'
                         f'<th style="text-align:right">Сбыв. прогноза</th><th>Вердикт</th></tr>{cal_table}</table>'))

    # ---------- воронки менеджеров ----------
    fun = A.get("funnel") or {}
    fun_cells = []
    for name, f in fun.items():
        if not (f.get("calls_fact") or f.get("kp_fact") or f.get("deals")):
            continue
        did = f"fun_{len(fun_cells)}"
        c2k = (f.get("conv_call_kp") or 0) * 100
        k2d = (f.get("conv_kp_deal") or 0) * 100
        div, js = ech_init(did, {
            "tooltip": {"trigger": "item", "formatter": "{b}: {c}"},
            "series": [{"type": "funnel", "sort": "descending", "gap": 3, "minSize": "16%", "maxSize": "94%",
                        "left": "6%", "width": "88%", "top": 8, "bottom": 8,
                        "label": {"show": True, "position": "inside", "fontSize": 10.5, "formatter": "{b}\n{c}", "color": "#fff"},
                        "itemStyle": {"borderWidth": 0, "borderRadius": 3},
                        "data": [
                            {"name": "Звонки", "value": f.get("calls_fact") or 0, "itemStyle": {"color": "#8a93d8"}},
                            {"name": "КП", "value": f.get("kp_fact") or 0, "itemStyle": {"color": INDIGO}},
                            {"name": "Договоры", "value": f.get("deals") or 0, "itemStyle": {"color": SLATE}},
                        ]}],
        }, height=190)
        charts_js.append(js)
        fun_cells.append(f'<div class="card" style="padding:10px 12px"><div style="text-align:center;'
                         f'font-weight:700;font-size:13px;margin-bottom:2px">{surname(name)}</div>{div}'
                         f'<div style="text-align:center;font-size:10.5px;color:var(--mut);font-family:var(--mono)">'
                         f'звонок→КП {c2k:.1f}% · КП→договор {k2d:.0f}%</div></div>')
    if fun_cells:
        cols = min(3, len(fun_cells))
        sections.append(("funnel", "воронка", False,
                         f'<div class="eyebrow">Воронка</div><h2>Звонки → КП → договоры (Q2, факт)</h2>'
                         f'<div style="display:grid;grid-template-columns:repeat({cols},1fr);gap:14px">{"".join(fun_cells)}</div>'))

    # ---------- исполнение по исполнителям (актирование; для СМК — аудиторы) ----------
    execs = A.get("executors") or []
    execs = [x for x in execs if (x.get("act_fact") or x.get("act_plan"))]
    if execs:
        top = execs[:14]
        names = [surname(x["executor"]) for x in top][::-1]
        plans = [x.get("act_plan") or 0 for x in top][::-1]
        facts = [x.get("act_fact") or 0 for x in top][::-1]
        cnts = [x.get("acts_count") or 0 for x in top][::-1]
        div, js = ech_init("exec_chart", {
            "grid": {"left": 110, "right": 70, "top": 28, "bottom": 24},
            "legend": {"data": ["план актов", "факт актов"], "top": 0, "textStyle": {"fontSize": 11}},
            "xAxis": {"type": "value", "axisLabel": {"show": False}, "splitLine": {"show": False}},
            "yAxis": {"type": "category", "data": names,
                      "axisLabel": {"fontSize": 11, "fontWeight": 600, "color": SLATE},
                      "axisTick": {"show": False}, "axisLine": {"show": False}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "series": [
                {"name": "план актов", "type": "bar", "data": plans, "barGap": "-100%", "barWidth": 15,
                 "itemStyle": {"color": "#e9e8e3", "borderRadius": 4}, "z": 1},
                {"name": "факт актов", "type": "bar", "data": facts, "barWidth": 8,
                 "itemStyle": {"color": GREEN, "borderRadius": 3}, "z": 2,
                 "label": {"show": True, "position": "right", "fontSize": 10,
                           "fontFamily": "Cascadia Mono,Consolas,monospace",
                           "formatter": "function"}},
            ],
        }, height=34 * len(top) + 56)
        js = js.replace('"formatter": "function"',
                        '"formatter": function(p){var c=' + json.dumps(cnts) +
                        ';return (p.value/1e6).toFixed(2)+"М · "+c[p.dataIndex]+" актов";}')
        charts_js.append(js)
        nfact = sum(1 for x in execs if x.get("act_fact"))
        loads = sorted((x.get("acts_count") or 0) for x in execs if x.get("acts_count"))
        imb = ""
        if len(loads) >= 4 and loads[-1] >= 3 * max(1, loads[0]):
            imb = (f' Перекос загрузки: топ — {loads[-1]:.0f} актов, часть — {loads[0]:.0f}. '
                   f'Недозагруженная мощность = упущенная выручка.')
        sections.append(("execs", "исполнители", False,
                         f'<div class="eyebrow">Исполнение</div><h2>Актирование по исполнителям</h2>'
                         f'<div class="lead">Кто закрывает работу актами (факт vs план, число актов). '
                         f'Всего исполнителей с актами: {nfact}.{imb}</div>'
                         f'<div class="card">{div}</div>'))

    # ---------- обещания: grounding (фантазии) или fact (обещано→факт) ----------
    kind = A.get("commitments_kind", "grounding")
    commits = A.get("commitments", [])
    disp_html = ""
    if kind == "grounding":
        fant = [c for c in commits if c.get("verdict") == "фантазия"]
        if fant:
            labels = [f'{surname(c["manager"])}: {(c["initiative"] or "")[:24]}' for c in fant][::-1]
            need = [c.get("kp_need") or 0 for c in fant][::-1]
            have = [c.get("kp_have") or 0 for c in fant][::-1]
            div, js = ech_init("disp", {
                "grid": {"left": 210, "right": 60, "top": 28, "bottom": 24},
                "legend": {"data": ["КП нужно", "КП есть"], "top": 0, "textStyle": {"fontSize": 11}},
                "xAxis": {"type": "value", "splitLine": {"lineStyle": {"color": "#f0efeb"}}, "axisLabel": {"fontSize": 10}},
                "yAxis": {"type": "category", "data": labels, "axisLabel": {"fontSize": 11.5, "color": SLATE},
                          "axisTick": {"show": False}, "axisLine": {"show": False}},
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "series": [
                    {"name": "КП нужно", "type": "bar", "data": need, "barWidth": 12,
                     "itemStyle": {"color": CRIMSON, "borderRadius": 3}, "label": {"show": True, "position": "right", "fontSize": 10.5}},
                    {"name": "КП есть", "type": "bar", "data": have, "barWidth": 12,
                     "itemStyle": {"color": GREEN, "borderRadius": 3}, "label": {"show": True, "position": "right", "fontSize": 10.5}},
                ],
            }, height=70 * len(fant) + 60)
            charts_js.append(js)
            items = "".join(f'<div class="uitem"><span class="n" style="color:{CRIMSON}">!</span><div>'
                            f'<b>{surname(c["manager"])}</b> · {esc(c["initiative"])} — обещано {money(c["expected"])}; '
                            f'нужно ~{c["kp_need"]} КП, есть {c["kp_have"]}.</div></div>' for c in fant)
            disp_html = div + f'<div style="margin-top:8px">{items}</div>'
        else:
            disp_html = '<div class="card" style="color:var(--mut)">Фантазий нет — все обещания подкреплены воронкой.</div>'
        disp_title = "Обещания, которые воронка не вытянет"
        disp_lead = "Красное — сколько КП нужно при текущем чеке и конверсии; зелёное — сколько есть."
    else:
        # fact-ось: обещано → факт по закрытым неделям
        from collections import Counter
        vc = Counter(c["verdict"] for c in commits)
        strip = ""
        for v, cls in [("сбылось", "g"), ("частично", "a"), ("не сбылось", "r"), ("тишина", "r"), ("в работе", "n")]:
            if vc.get(v):
                strip += f'<span class="age {cls}" style="font-size:12px;padding:4px 12px">{v}: {vc[v]}</span> '
        bad = [c for c in commits if c["verdict"] in ("не сбылось", "частично")]
        bad = sorted(bad, key=lambda c: -(c["expected"] or 0))[:8]
        chart = ""
        if bad:
            labels = [f'{surname(c["manager"])}: {(c["initiative"] or "")[:22]}' for c in bad][::-1]
            exp = [c.get("expected") or 0 for c in bad][::-1]
            fct = [c.get("fact") or 0 for c in bad][::-1]
            div, js = ech_init("disp", {
                "grid": {"left": 200, "right": 96, "top": 28, "bottom": 24},
                "legend": {"data": ["обещано", "факт"], "top": 0, "textStyle": {"fontSize": 11}},
                "xAxis": {"type": "value", "axisLabel": {"show": False}, "splitLine": {"show": False}},
                "yAxis": {"type": "category", "data": labels, "axisLabel": {"fontSize": 11, "color": SLATE},
                          "axisTick": {"show": False}, "axisLine": {"show": False}},
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "series": [
                    {"name": "обещано", "type": "bar", "data": exp, "barGap": "-100%", "barWidth": 15,
                     "itemStyle": {"color": "#e9e8e3", "borderRadius": 4}, "z": 1},
                    {"name": "факт", "type": "bar", "data": fct, "barWidth": 8,
                     "itemStyle": {"color": CRIMSON, "borderRadius": 3}, "z": 2,
                     "label": {"show": True, "position": "right", "fontSize": 10,
                               "fontFamily": "Cascadia Mono,Consolas,monospace", "formatter": "{c}"}},
                ],
            }, height=52 * len(bad) + 56)
            charts_js.append(js)
            chart = div
        items = "".join(f'<div class="uitem"><span class="n" style="color:{CRIMSON}">!</span><div>'
                        f'<b>{surname(c["manager"])}</b> · {esc(c["initiative"])} — обещано {money(c["expected"])}, '
                        f'факт {money(c["fact"])} <span class="pill r">{esc(c["verdict"])}</span></div></div>' for c in bad)
        disp_html = (f'<div style="margin-bottom:14px">{strip}</div>' + chart +
                     (f'<div style="margin-top:8px">{items}</div>' if items else
                      '<div class="card" style="color:var(--mut)">Все закрытые обещания выполнены.</div>'))
        disp_title = "Обещано → факт: что недозакрыто"
        disp_lead = "Серая полоса — обещанный эффект недели; красная — фактическая контрактация. Разрыв = недобор."
    if disp_html:
        sections.append(("dispute", "обещания", False,
                         f'<div class="eyebrow">Обещания vs реальность</div><h2>{disp_title}</h2>'
                         f'<div class="lead">{disp_lead}</div>{disp_html}'))

    # ---------- SMART-контроль ----------
    sc = A.get("smart_control")
    if sc and sc.get("rows"):
        s = sc["summary"]
        sc_cls = "r" if (s["avg_score"] or 0) < 50 else ("a" if s["avg_score"] < 80 else "g")
        fq = sc.get("funnel_week", {})
        fq_warn = (f'<div class="alert warn" style="border:1px solid var(--line);border-radius:12px;margin-bottom:12px">'
                   f'<span class="atag">Воронка</span><div>{esc(fq.get("note"))}</div></div>') if fq.get("note") else ""
        head = (f'<div class="scsum"><span class="scscore {sc_cls}">{s["avg_score"]}</span>'
                f'<div>средний балл недели · конкретных {s["ok"]} / доработать {s["rework"]} / «тема» {s["trash"]}'
                f'<div style="font-size:11px;color:var(--mut);font-weight:400">балл: глагол 20 · ₽ 15 · срок 15 · '
                f'продукт 15 · клиент 10 · рычаг 5 · реалистичность 20</div></div></div>')
        rows_html = ""
        for r in sc["rows"]:
            v_cls = "r" if r["verdict"] == "тема, не действие" else ("a" if r["score"] < 80 else "g")
            misses = [c["note"] for c in r["checks"].values() if c["note"] and not c["ok"]]
            chips = "".join(f'<span class="miss">{esc(n)}</span>' for n in misses)
            rw = (f'<div class="rwline"><span class="rwlab">как надо</span>{esc(r["rewrite"])}</div>' if r.get("rewrite") else "")
            rows_html += (f'<div class="scrow"><div class="schead"><span class="scbadge {v_cls}">{r["score"]}</span>'
                          f'<b>{surname(r["manager"])}</b> · «{esc(r["initiative"])}» · {money(r["expected"])}'
                          f'<span class="pill {v_cls}" style="margin-left:auto">{esc(r["verdict"])}</span></div>'
                          f'<div class="misses">{chips}</div>{rw}</div>')
        sections.append(("smart", "SMART", False,
                         f'<div class="eyebrow">SMART-контроль</div><h2>Недельный реестр: качество формулировок</h2>'
                         f'<div class="lead">Каждая строка проверена: глагол · ₽ · срок · продукт · клиент · рычаг · '
                         f'реалистичность. Зелёный шаблон — «как надо» для планёрки.</div>{fq_warn}{head}{rows_html}'))

    # ---------- журнал обещаний (ledger) ----------
    led = A.get("ledger")
    if led:
        ls = led["summary"]
        ledger_html = (f'<div class="ledsum">'
                       f'<div class="kpi"><div class="lbl">Открыто обещаний</div><div class="val">{ls["open"]} · {money(ls["promised_open_sum"])}</div></div>'
                       f'<div class="kpi"><div class="lbl">Висят 3+ недели</div><div class="val" style="color:{CRIMSON}">{ls["stuck"]}</div></div>'
                       f'<div class="kpi"><div class="lbl">Закрыто</div><div class="val" style="color:{GREEN}">{ls["closed"]}</div></div>'
                       f'<div class="kpi"><div class="lbl">Пропало без закрытия</div><div class="val" style="color:{AMBER}">{ls["vanished"]}</div></div></div>')
        lrows = ""
        for r in led["rows"]:
            age = r["weeks_open"]
            a_cls = "g" if r["closed"] else ("r" if age >= 3 else ("a" if age == 2 else "n"))
            age_lbl = "закрыто" if r["closed"] else ("пропало" if r["vanished"] else f"{age}-я нед")
            lrows += (f'<tr><td><span class="age {a_cls}">{age_lbl}</span></td><td><b>{surname(r["manager"])}</b></td>'
                      f'<td>{esc(r["initiative"])}</td><td class="num">{money(r["expected"])}</td>'
                      f'<td>{esc(r.get("status_now") or "—")}</td>'
                      f'<td class="num">{money(r["fact"]) if r.get("fact") is not None else "—"}</td></tr>')
        sections.append(("ledger", "журнал", False,
                         f'<div class="eyebrow">Журнал обещаний</div><h2>Судьба обещаний во времени</h2>'
                         f'<div class="lead">Каждый прогон снимает реестр в журнал: новое, висящее 3-ю неделю, '
                         f'закрытое — и тихо пропавшее.</div>{ledger_html}'
                         f'<div class="card" style="padding:6px 14px;margin-top:14px"><table>'
                         f'<tr><th>Возраст</th><th>Менеджер</th><th>Обещание</th><th style="text-align:right">Ожид. ₽</th>'
                         f'<th>Статус</th><th style="text-align:right">Факт ₽</th></tr>{lrows}</table></div>'))

    # ---------- конкуренты ----------
    cp = A.get("competitors", {})
    if cp.get("top_rivals"):
        rivals_html = "".join(f'<div class="rchip"><b>{esc(r["name"])}</b> <span class="cnt">×{r["appears"]}</span>'
                              + (f' <span class="nt">— {esc(r["note"])}</span>' if r.get("note") else "") + '</div>'
                              for r in cp.get("top_rivals", []))
        comp_rows = "".join(f'<tr><td><b>{esc(p["product"])}</b></td><td class="num">{esc(p.get("avg_check") or "—")}</td>'
                            f'<td>{esc(", ".join(p["competitors"]))}</td></tr>' for p in cp.get("by_product", []))
        pos_html = (f'<div class="poscols"><div class="posbox edge"><h4>Наше преимущество</h4>{esc(cp.get("our_edge"))}</div>'
                    f'<div class="posbox gap"><h4>Слабые места — закрывать</h4>{esc(cp.get("our_gap"))}</div></div>'
                    if cp.get("our_edge") or cp.get("our_gap") else "")
        sections.append(("rivals", "конкуренты", False,
                         f'<div class="eyebrow">Конкуренты</div><h2>С кем боремся и чем берём</h2>'
                         f'<div class="lead">Из 00-слоя, по каждому продукту. ×N — в скольких продуктах встречается соперник.</div>'
                         f'<div class="rivals">{rivals_html}</div>'
                         f'<div class="card" style="padding:6px 14px"><table><tr><th>Продукт</th>'
                         f'<th style="text-align:right">Средний чек</th><th>Конкуренты</th></tr>{comp_rows}</table></div>{pos_html}'))

    # ---------- сезонность ----------
    sea = A.get("seasonality", {})
    prods = [s for s in sea.get("products", []) if s.get("strength") and s["strength"] != "нет"]
    if prods:
        qs = ["Q1", "Q2", "Q3", "Q4"]
        yn = [p["name"][:26] for p in prods][::-1]
        smap = {"сильная": 2, "есть": 1, "слабая": 1}
        data = []
        for yi, p in enumerate(prods[::-1]):
            for qi, q in enumerate(qs):
                v = smap.get(p["strength"], 0) if q in (p.get("quarters") or []) else 0
                data.append([qi, yi, v])
        div, js = ech_init("seasonhm", {
            "grid": {"left": 200, "right": 30, "top": 26, "bottom": 24},
            "xAxis": {"type": "category", "data": ["Q1", "Q2 · сейчас", "Q3", "Q4"], "position": "top",
                      "axisLabel": {"fontSize": 11, "fontWeight": 600}, "axisTick": {"show": False},
                      "axisLine": {"show": False}, "splitArea": {"show": True}},
            "yAxis": {"type": "category", "data": yn, "axisLabel": {"fontSize": 11, "color": SLATE},
                      "axisTick": {"show": False}, "axisLine": {"show": False}},
            "visualMap": {"show": False, "min": 0, "max": 2, "inRange": {"color": ["#f2f1ed", AMBER, CRIMSON]}},
            "tooltip": {"formatter": "{b}"},
            "series": [{"type": "heatmap", "data": data, "itemStyle": {"borderColor": "#fff", "borderWidth": 2, "borderRadius": 4},
                        "emphasis": {"itemStyle": {"shadowBlur": 6, "shadowColor": "rgba(0,0,0,.2)"}}}],
        }, height=30 * len(yn) + 60)
        charts_js.append(js)
        legend = (f'<div style="font-size:11px;color:var(--mut);margin-top:4px;font-family:var(--mono)">'
                  f'<span style="color:{CRIMSON}">■</span> сильная сезонность · '
                  f'<span style="color:{AMBER}">■</span> слабая/есть · серый — вне сезона</div>')
        sections.append(("season", "сезонность", False,
                         f'<div class="eyebrow">Сезонный радар</div><h2>Когда пик спроса по продуктам</h2>'
                         f'<div class="card">{div}{legend}</div>'))

    # ---------- регуляторный радар ----------
    rad = A.get("radar", {})
    radar_html = ""
    for it in rad.get("push_now", []):
        radar_html += (f'<div class="rcard push"><div class="rt">🟢 Продавать: {esc(", ".join(it["products"]))}</div>'
                       f'<div class="rd">{esc(it["obligation"])}</div>'
                       f'<div class="rdl">{esc(it["title"])} → {esc(it["deadline"])} (через {it["weeks"]} нед.)</div></div>')
    for it in rad.get("product_gaps", []):
        hot = "🔥 " if (it.get("weeks") is not None and it["weeks"] <= 8) else ""
        dl = f'{it["deadline"]} (через {it["weeks"]} нед.)' if it.get("deadline") else "—"
        radar_html += (f'<div class="rcard gap"><div class="rt">{hot}Пробел: {esc(it["title"])}</div>'
                       f'<div class="rd">{esc(it["obligation"])} — продукта нет</div><div class="rdl">{dl}</div></div>')
    if radar_html:
        sections.append(("radar", "радар", False,
                         f'<div class="eyebrow">Регуляторный радар · {esc(rad.get("source",""))}</div>'
                         f'<h2>Что продавать под дедлайн · пробелы</h2><div class="radar2">{radar_html}</div>'))

    # ---------- тендеры ----------
    tn = A.get("tenders")
    if tn:
        act_cards = ""
        for t in tn.get("active", [])[:8]:
            price = money(t["price"]) if t.get("price") else "цена не указана"
            act_cards += (f'<div class="rcard push"><div class="rt">{esc((t.get("object") or "")[:110])}</div>'
                          f'<div class="rd">{esc((t.get("customer") or "")[:90])}</div>'
                          f'<div class="rdl">{price} · {esc(t.get("law") or "")} · размещено {esc(t.get("placed") or "")} · '
                          f'<a href="{esc(t.get("url"))}" target="_blank" style="color:var(--indigo)">открыть в ЕИС →</a></div></div>')
        if not act_cards:
            act_cards = '<div class="card" style="color:var(--mut)">Активных профильных тендеров в окне подачи нет.</div>'
        arch_rows = "".join(
            f'<tr><td>{esc((t.get("object") or "")[:80])}</td><td>{esc((t.get("customer") or "")[:55])}</td>'
            f'<td class="num">{money(t["price"]) if t.get("price") else "—"}</td>'
            f'<td class="num">{esc((t.get("placed") or "")[-4:])}</td></tr>' for t in tn.get("archive", [])[:8])
        arch_html = (f'<details style="margin-top:14px"><summary style="cursor:pointer;font-size:13px;font-weight:600">'
                     f'Карта рынка из архива ЕИС ({tn.get("found_archive", 0)})</summary>'
                     f'<div class="card" style="padding:6px 14px;margin-top:10px"><table>'
                     f'<tr><th>Объект</th><th>Заказчик</th><th style="text-align:right">Цена</th>'
                     f'<th style="text-align:right">Год</th></tr>{arch_rows}</table></div></details>') if arch_rows else ""
        sections.append(("tenders", "тендеры", False,
                         f'<div class="eyebrow">Тендеры · {esc(tn.get("source", "ЕИС"))}</div>'
                         f'<h2>Госзакупки под наши продукты — B2G-лиды</h2>'
                         f'<div class="lead">Живой поиск ЕИС, шум отфильтрован. Активных: {tn.get("found_active", 0)}.</div>'
                         f'{act_cards}{arch_html}'))

    # ---------- конвейер действий ----------
    pipe_rows = "".join(f'<tr><td class="pn">{i+1}</td>'
                        f'<td><b>{esc(a["action"])}</b><div class="bs">основание: {esc(a["basis"])}</div></td>'
                        f'<td><span class="ow">{esc(a["owner"])}</span></td><td class="dl">{esc(a["deadline"])}</td>'
                        f'<td>{esc(a["effect"])}</td></tr>' for i, a in enumerate(A.get("action_pipeline", [])))
    if pipe_rows:
        sections.append(("actions", "действия", False,
                         f'<div class="eyebrow">Конвейер действий</div><h2>Что делать в следующем периоде</h2>'
                         f'<div class="lead">Каждое действие: основание из данных · ответственный · срок · ожидаемый эффект.</div>'
                         f'<div class="card" style="padding:6px 14px"><table class="pipe"><tr><th>#</th><th>Действие</th>'
                         f'<th>Ответств.</th><th>Срок</th><th>Эффект</th></tr>{pipe_rows}</table></div>'))

    # ---------- сборка ----------
    nav_html = "".join(f'<a href="#{sid}" class="{"hot" if hot else ""}">{lbl}</a>'
                       for sid, lbl, hot, _ in sections if sid != "urgent")
    demo_badge = ('<span style="background:#fcf1e0;color:#9a6512;font-size:10px;font-weight:700;'
                  'padding:2px 8px;border-radius:6px;margin-left:8px">ДЕМО · данные обезличены</span>') if demo else ""
    # алерты ведут повестку (до героя); остальное — после
    alerts_sec = next((x for x in sections if x[0] == "alerts"), None)
    alerts_block = (f'<div class="sec" id="alerts" style="margin-top:22px">{alerts_sec[3]}</div>'
                    if alerts_sec else "")
    body_secs = "".join(f'<div class="sec" id="{sid}">{html}</div>'
                        for sid, lbl, hot, html in sections if sid != "alerts")

    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI-Findir · {esc(title)} Q2 2026{' · ДЕМО' if demo else ''}</title>
<style>{CSS}</style></head><body><div class="wrap">

<div class="top">
  <div><div class="brand">AI-<b>Findir</b> · управленческая сводка{demo_badge}</div>
  <div class="h1">{esc(dept)} — {dg["period"]}</div></div>
  <div class="top-meta">контроль: {dg["control_date"]}<br>источник: analysis.json<br>факт: апрель, май · прогноз: июнь</div>
</div>
<nav class="nav">{nav_html}</nav>
{alerts_block}
<div class="hero2" id="hero">
  <div class="left">
    <div class="lbl">Операционный финрез Q2</div>
    <div class="big">{money(dg["finrez"])}</div>
    <div class="sub">{esc(fb.get("reading") if fb else "")}</div>
    <div class="kpis">
      <div class="k"><div class="v">{short(dg["revenue_acts"]).lstrip("+")}</div><div class="l">акты</div></div>
      <div class="k"><div class="v">{short(dg["expenses"]).lstrip("+")}</div><div class="l">расходы</div></div>
      <div class="k"><div class="v" style="color:{CRIMSON}">{short(dg["deficit_to_zero"]).lstrip("+")}</div><div class="l">до нуля</div></div>
    </div>
  </div>
  <div class="right"><div class="cap">план-факт мост: откуда взялся минус (наведи на столбик)</div>{wf_div}</div>
</div>

{body_secs}

<div class="foot">
  <div>Единый источник: analysis.json · отдел {esc(title)}{' · ДЕМО (обезличено)' if demo else ''}</div>
  <div>AI-Findir · Дашборд 2.0 · ECharts офлайн</div>
</div>

</div>
<script>{ECHARTS_JS}</script>
<script>
{chr(10).join(charts_js)}
window.addEventListener('resize',function(){{document.querySelectorAll('.chart').forEach(function(el){{var c=echarts.getInstanceByDom(el);if(c)c.resize();}});}});
</script>
</body></html>"""

    out = os.path.join(OUT, slug, "demo.html" if demo else "dashboard.html")
    open(out, "w", encoding="utf-8").write(html)
    return out, len(html), len(charts_js), len(sections)


if __name__ == "__main__":
    slugs = sys.argv[1:] or ["eco", "prod", "uc"]
    for s in slugs:
        out, size, ncharts, nsec = render(s)
        print(f"[{s}] -> {out} ({size/1e6:.2f} MB, графиков {ncharts}, секций {nsec})")
