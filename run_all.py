# -*- coding: utf-8 -*-
"""
run_all — единый прогон AI-Findir по ВСЕМ отделам из raw/.

Запуск одной командой: `python run_all.py`. Файлы отделов ищутся в raw/ по шаблону
(самый свежий по дате в имени); дата контроля/период/закрытые месяцы — авто (depts.py).
Ничего в коде руками править не нужно: положил xlsx в raw/ → запустил.

Для каждого отдела (depts.py):
  build_dept → контракт out/<slug>/analysis.json
  agents     → LLM-разбор 03/04 вшивается в контракт (best-effort; --stub офлайн)
  dash       → реальный дашборд out/<slug>/dashboard.html
  anonymize  → обезличенный контракт out/<slug>/analysis_demo.json
  dash(demo) → публичное демо out/<slug>/demo.html
  leak-gate  → проверка, что в демо НЕ просочились реальные ФИО/клиенты

Плюс свод собственнику (owner.html / owner_demo.html), out/index.html (навигация)
и out/MANIFEST.txt (сводка прогона). Демо безопасно публиковать; реальные файлы
(analysis.json, dashboard.html, owner.html, raw/) наружу не идут.
"""
import os
import re
import sys
import json

import build_dept
import dash
import anonymize
import owner
import run_agents
import analysis_render
from depts import DEPTS, ORDER, OUT, CONTROL_DATE
from theme_findir import CSS, money, esc

# LLM-разбор (агенты 03/04) гоним через Claude CLI; --stub или AIF_AGENTS_STUB=1 — офлайн-заглушка.
AGENTS_STUB = ("--stub" in sys.argv) or bool(os.environ.get("AIF_AGENTS_STUB"))

# структурные сигнатуры утечки в ЗНАЧЕНИЯХ демо-контракта (не в json-дампе!):
GATE_QUOTED_RX = re.compile(r'"[А-ЯЁ][^"\n]{2,45}"')
GATE_PREFIX_RX = re.compile(
    r'(?:ООО|ОАО|АО|ПАО|ЗАО|ГК|НПО|НПП|НПЦ|ФГУП|ФКП|АНО|ГКУ|ГБУ|МПО|ОАК|ИП|НАЗ|КАПО)\s+'
    r'(?!«Клиент)["«А-ЯЁ][^,;:()\n]{2,40}')


def leak_gate(slug):
    real = json.load(open(os.path.join(OUT, slug, "analysis.json"), encoding="utf-8"))
    demo = json.load(open(os.path.join(OUT, slug, "analysis_demo.json"), encoding="utf-8"))
    name_map, _ = anonymize.build_name_map(real)        # реальные основы фамилий
    leaks = set()
    # блок конкурентов пропускаем: публичные участники рынка остаются намеренно
    for v in anonymize.iter_strings(demo, skip="competitors"):   # только строковые значения
        for st in name_map:                             # 1) остаток реальной фамилии
            if st in v:
                leaks.add(st)
        for m in GATE_QUOTED_RX.findall(v):             # 2) необезличенный оргназвание
            leaks.add(m[:32])
        for m in GATE_PREFIX_RX.findall(v):             # 3) орг-префикс + имя
            leaks.add(m[:32])
        for m in anonymize.PERSON_INITIALS_RX.findall(v):   # 4) третье лицо «Фамилия И.О.»
            if m.split()[0] not in anonymize.FAKE_SURNAMES:
                leaks.add(m[:32])
    return sorted(leaks)


def owner_leak_gate():
    """Свод собственнику (owner_demo.html) строится из *_demo.json, но на всякий случай
    сканируем готовый HTML на остатки реальных фамилий из всех 4 реальных контрактов."""
    name_map = {}
    for slug in ORDER:
        real = json.load(open(os.path.join(OUT, slug, "analysis.json"), encoding="utf-8"))
        nm, _ = anonymize.build_name_map(real)
        name_map.update(nm)
    html = open(os.path.join(OUT, "owner_demo.html"), encoding="utf-8").read()
    return sorted({st for st in name_map if st in html})


def write_index(results):
    company = json.load(open(os.path.join(OUT, ORDER[0], "analysis.json"), encoding="utf-8"))["meta"].get("company", "—")
    cards = ""
    for slug in ORDER:
        r = results[slug]
        dg = r["diag"]
        cards += f"""
        <div class="card">
          <div class="dep">{esc(DEPTS[slug]['name'])}</div>
          <div class="fr">{money(dg['finrez'])}</div>
          <div class="meta">контрактация {round((dg.get('contract_pct') or 0)*100)}% ·
            дефицит до нуля {money(dg['deficit_to_zero'])}</div>
          <div class="links">
            <a class="real" href="{slug}/dashboard.html">Дашборд (реальный)</a>
            <a class="demo" href="{slug}/demo.html">Демо (обезличено)</a>
          </div>
          <div class="cnt">{r['charts']} графиков · {r['sections']} секций ·
            обещаний {r['commits']} · алертов {r['alerts']}</div>
        </div>"""
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI-Findir · отделы Q2 2026</title><style>{CSS}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px;margin-top:24px}}
.card .dep{{font-family:var(--display);font-size:20px;font-weight:700}}
.card .fr{{font-family:var(--display);font-size:32px;font-weight:700;color:var(--crimson);margin:6px 0}}
.card .meta{{font-size:12.5px;color:var(--mut)}}
.card .links{{display:flex;gap:10px;margin:14px 0 8px}}
.card .links a{{flex:1;text-align:center;padding:9px 12px;border-radius:10px;font-size:13px;font-weight:600;text-decoration:none}}
.card .links a.real{{background:var(--indigo);color:#fff}}
.card .links a.demo{{background:#eef0fb;color:var(--indigo);border:1px solid var(--line)}}
.card .cnt{{font-family:var(--mono);font-size:11px;color:var(--mut)}}
</style></head><body><div class="wrap">
<div class="top"><div><div class="brand">AI-<b>Findir</b> · управленческая сводка</div>
<div class="h1">Отделы — {esc(company)} · {CONTROL_DATE[:4]}</div></div>
<div class="top-meta">единый движок · {len(ORDER)} отдела<br>контроль: {CONTROL_DATE}</div></div>
<div class="sec"><div class="eyebrow">Свод собственнику</div>
<div class="lead">Портфель целиком одним экраном: финрез всех отделов, рейтинг, кому верить,
что оспорить, что пушить.</div>
<div class="links" style="display:flex;gap:10px;margin-top:12px;max-width:520px">
<a class="real" href="owner.html" style="flex:1;text-align:center;padding:11px;border-radius:10px;background:var(--crimson);color:#fff;font-weight:600;text-decoration:none">Свод собственнику (реальный)</a>
<a class="demo" href="owner_demo.html" style="flex:1;text-align:center;padding:11px;border-radius:10px;background:#fff3f4;color:var(--crimson);border:1px solid #f3c9cd;font-weight:600;text-decoration:none">Свод (демо)</a>
</div></div>
<div class="sec"><div class="eyebrow">Навигация по отделам</div>
<div class="lead">Один движок (extract → контракт → дашборд) на все отделы. «Реальный» —
рабочий дашборд по фактическим данным; «Демо» — обезличенная версия для показа.</div>
<div class="grid">{cards}</div></div>
<div class="foot"><div>Единый источник: out/&lt;отдел&gt;/analysis.json</div>
<div>AI-Findir · унифицированный движок</div></div>
</div></body></html>"""
    p = os.path.join(OUT, "index.html")
    open(p, "w", encoding="utf-8").write(html)
    return p


def main():
    os.makedirs(OUT, exist_ok=True)
    results = {}
    log = ["#" * 78, "ПОЛНЫЙ ПРОГОН AI-FINDIR — все отделы (единый движок)", "#" * 78, ""]
    all_ok = True

    for slug in ORDER:
        A, cpath = build_dept.build(slug)
        agent_res = run_agents.run_for_dept(slug, stub=AGENTS_STUB)   # LLM-разбор → вшит в контракт
        d_out, d_size, d_charts, d_sec = dash.render(slug, demo=False)
        analysis_render.inject(d_out, os.path.join(OUT, slug, "analysis.json"))
        anonymize.anonymize(slug)
        m_out, m_size, m_charts, m_sec = dash.render(slug, demo=True)
        analysis_render.inject(m_out, os.path.join(OUT, slug, "analysis_demo.json"))
        leaks = leak_gate(slug)
        dg = A["diagnosis"]
        results[slug] = {"diag": dg, "charts": d_charts, "sections": d_sec,
                         "commits": len(A.get("commitments", [])), "alerts": len(A.get("alerts", [])),
                         "leaks": leaks}
        status = "OK" if not leaks else f"!!! УТЕЧКА: {leaks}"
        if leaks:
            all_ok = False
        log.append(f"[{slug}] {DEPTS[slug]['name']}")
        log.append(f"   финрез {money(dg['finrez'])} | контрактация "
                   f"{round((dg.get('contract_pct') or 0)*100)}% | дефицит {money(dg['deficit_to_zero'])}")
        log.append(f"   дашборд: {d_charts} граф / {d_sec} секц / {d_size/1e6:.2f}МБ | "
                   f"демо: {m_charts} граф / {m_size/1e6:.2f}МБ")
        log.append(f"   обещаний {len(A.get('commitments', []))} ({A.get('commitments_kind')}) | "
                   f"smart {bool(A.get('smart_control'))} | ledger {bool(A.get('ledger'))} | "
                   f"funnel {bool(A.get('funnel'))}")
        log.append(f"   leak-gate: {status}")
        log.append("   агенты: " + " | ".join(f"{c}:{m}" for c, m in agent_res.items()))
        log.append("")

    # ---- свод собственнику (real + demo) поверх готовых контрактов ----
    o_out, o_size, o_ch, o_sec = owner.render(demo=False)
    od_out, od_size, od_ch, od_sec = owner.render(demo=True)
    o_leaks = owner_leak_gate()
    o_status = "OK" if not o_leaks else f"!!! УТЕЧКА: {o_leaks}"
    if o_leaks:
        all_ok = False
    log.append("[owner] Свод собственнику (портфель)")
    log.append(f"   финрез портфеля {money(sum(results[s]['diag']['finrez'] for s in ORDER))} | "
               f"секций {o_sec} | real {o_size/1e6:.2f}МБ / demo {od_size/1e6:.2f}МБ")
    log.append(f"   leak-gate: {o_status}")
    log.append("")

    idx = write_index(results)
    log.append(f"index -> {idx}")
    log.append(f"owner -> {o_out}")
    log.append(f"owner_demo -> {od_out}")
    log.append("")
    log.append("#" * 78)
    log.append("ИТОГ: " + ("ВСЕ ОТДЕЛЫ ОК, демо чистые" if all_ok else "ЕСТЬ УТЕЧКИ — СМОТРИ ВЫШЕ"))
    log.append("#" * 78)

    manifest = os.path.join(OUT, "MANIFEST.txt")
    open(manifest, "w", encoding="utf-8").write("\n".join(log))
    print("\n".join(log))
    print("\nmanifest ->", manifest, "| all_ok =", all_ok)
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
