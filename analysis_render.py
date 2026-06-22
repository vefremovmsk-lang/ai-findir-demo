# -*- coding: utf-8 -*-
"""
analysis_render — врезка секций LLM-разбора в готовый дашборд БЕЗ правки dash.py.

dash.py рендерит дашборд по цифрам; этот модуль добавляет поверх секции анализа
из контракта (A["analysis"]["action" | "competitive"]) — вставляет перед футером.
Идемпотентно: повторная врезка заменяет прежнюю. Минимальный md→html для текста агента.
"""
import re
import json
import html as _h

_ST = "border-left:3px solid var(--indigo);padding-left:16px;margin-top:6px"


def md2html(md):
    def inline(t):
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _h.escape(t))
    out, in_ul = [], False
    for raw in (md or "").splitlines():
        t = raw.strip()
        if not t:
            if in_ul:
                out.append("</ul>"); in_ul = False
            continue
        if t.startswith(("- ", "* ")):
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{inline(t[2:].strip())}</li>"); continue
        if in_ul:
            out.append("</ul>"); in_ul = False
        m = re.match(r"(#{1,4})\s+(.*)", t)
        if m:
            lvl = min(len(m.group(1)) + 1, 4)
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); continue
        out.append(f"<p>{inline(t)}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def _sec(eyebrow, h2, md):
    return (f'<div class="sec"><div class="eyebrow">{eyebrow}</div><h2>{h2}</h2>'
            f'<div style="{_ST}">{md2html(md)}</div></div>')


def inject(html_path, contract_path):
    """Врезать секции разбора из контракта в html перед футером. -> True, если что-то вставлено."""
    an = json.load(open(contract_path, encoding="utf-8")).get("analysis", {})
    blocks = ""
    if an.get("action"):
        blocks += _sec("Разбор аналитика — ИИ поверх контракта", "Что это значит и что делать", an["action"])
    if an.get("competitive"):
        blocks += _sec("Конкуренты — живой анализ (ИИ)", "Сравнение с рынком и 3 отличия", an["competitive"])
    if not blocks:
        return False
    html = open(html_path, encoding="utf-8").read()
    html = re.sub(r'<div id="analysis-block">.*?<!--/analysis-->', "", html, flags=re.S)  # идемпотентность
    wrap = f'<div id="analysis-block">{blocks}</div><!--/analysis-->'
    html = html.replace('<div class="foot">', wrap + '<div class="foot">', 1)
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html); fh.flush()
        import os
        os.fsync(fh.fileno())
    return True
