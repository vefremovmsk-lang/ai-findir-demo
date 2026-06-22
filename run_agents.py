# -*- coding: utf-8 -*-
"""
run_agents — слой LLM-АНАЛИЗА поверх детерминированного контракта.

Смысл проекта: код считает цифры (build_dept), а АГЕНТЫ их АНАЛИЗИРУЮТ. Этот модуль
для каждого отдела берёт готовый контракт out/<slug>/analysis.json и прогоняет агентов:
  • 03 Action Advisor    — недельный разбор: кому верить, что оспорить, риски, след. шаг.
  • 04 Competitive Judge — сравнение с конкурентами + 3 отличия (вход: сырой markdown из
                           competitors/<направление>/, собранный competitor_scan.py).
Результат каждого агента проходит verify_numbers (деньги обязаны существовать в контракте),
и при успехе ВШИВАЕТСЯ в контракт: A["analysis"]["action" | "competitive"]. Дальше dash/owner
рисуют секцию «Разбор аналитика» поверх цифр.

LLM — Claude CLI (`claude --print`, подписка Claude Max), без доп. ключей. Best-effort:
если CLI недоступен — разбор пропускается, дашборд всё равно собирается. Режим --stub
гоняет обвязку офлайн (без LLM) детерминированной заглушкой на реальных числах контракта.

Использование:
  встроено в run_all.py (run_for_dept). Отдельно: python run_agents.py [--stub]
"""
import os
import re
import sys
import json
import subprocess

from depts import ORDER, OUT, DEPTS

LAB = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.join(LAB, "agents_v2")
PROMPTS_DIR = os.path.join(LAB, "agent_prompts")
OUT_DIR = os.path.join(LAB, "agent_outputs")
COMP_DIR = os.path.join(LAB, "competitors")
os.makedirs(PROMPTS_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

from verify_numbers import verify_text

# отдел -> подпапка собранных конкурентов (есть данные только там, где гоняли competitor_scan)
COMP_SUBDIR = {"eco": "eco"}

# агенты: (код, спека, ключ в A["analysis"], нужен ли вход-конкуренты, задача)
AGENTS = [
    ("03", "03_action_advisor.md", "action", False,
     "Сгенерируй недельный разбор для собственника строго по своей спецификации."),
    ("04", "04_market_competitive_judge.md", "competitive", True,
     "Дай сравнение с конкурентами и ровно 3 отличия по каждому, строго по своей спецификации."),
]


def _competitor_md(slug):
    """Собранный сырой markdown конкурентов для отдела (склейка непустых страниц)."""
    sub = COMP_SUBDIR.get(slug)
    if not sub:
        return ""
    d = os.path.join(COMP_DIR, sub)
    if not os.path.isdir(d):
        return ""
    chunks = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".md"):
            p = os.path.join(d, fn)
            txt = open(p, encoding="utf-8").read().strip()
            if txt:
                chunks.append(f"### Источник: {fn}\n{txt[:8000]}")
    return "\n\n".join(chunks)


def build_prompt(slug, spec_file, task, with_comp):
    spec = open(os.path.join(AGENTS_DIR, spec_file), encoding="utf-8").read()
    a_text = open(os.path.join(OUT, slug, "analysis.json"), encoding="utf-8").read()
    extra = ""
    if with_comp:
        md = _competitor_md(slug)
        extra = (f"\n\n## ВХОД — собранный markdown конкурентов (источник фактов, не выдумывать)\n\n"
                 f"{md if md else '(нет собранных данных — для этого отдела competitor_scan не гонялся)'}\n")
    return (f"{spec}\n\n---\n\n## ВХОД — analysis.json отдела «{DEPTS[slug]['name']}» "
            f"(единственный источник чисел, не пересчитывать)\n\n```json\n{a_text}\n```{extra}\n\n"
            f"## ЗАДАЧА\n{task}\nИспользуй ТОЛЬКО данные выше. Markdown без преамбулы.\n")


def run_claude(prompt_text):
    """Claude CLI через stdin (PowerShell). Возврат (output|None, err)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "claude --print --dangerously-skip-permissions"],
            input=prompt_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300)
        out = (r.stdout or "").strip()
        blob = (out + " " + (r.stderr or "")).lower()
        if r.returncode != 0 or "authenticate" in blob or "401" in blob or not out:
            return None, ((r.stderr or out).strip() or f"exit {r.returncode}")[:160]
        return out, None
    except Exception as e:
        return None, repr(e)[:160]


def stub_output(slug, code, A):
    """Детерминированная заглушка на РЕАЛЬНЫХ числах контракта (для офлайн-проверки обвязки)."""
    dg = A.get("diagnosis", {})
    fr, dfc = dg.get("finrez"), dg.get("deficit_to_zero")
    if code == "03":
        return (f"## Разбор (заглушка)\n\nОперационный финрез **{fr} ₽**, до нуля не хватает "
                f"**{dfc} ₽**. Это демо-текст обвязки: на твоей машине здесь будет живой разбор "
                f"агента 03 (кому верить, что оспорить, следующий шаг).\n")
    return (f"## Конкуренты (заглушка)\n\nСравнение по направлению «{DEPTS[slug]['title']}». "
            f"Дефицит до нуля **{dfc} ₽**. Это демо-текст обвязки: на твоей машине здесь будет "
            f"живой анализ агента 04 (услуги, ценники, позиционирование, новые продукты, 3 отличия).\n")


def run_for_dept(slug, stub=False):
    """Прогнать агентов по отделу, вшить прошедший verify разбор в контракт. -> сводка по отделу."""
    cpath = os.path.join(OUT, slug, "analysis.json")
    A = json.load(open(cpath, encoding="utf-8"))
    A.setdefault("analysis", {})
    odir = os.path.join(OUT_DIR, slug)
    os.makedirs(odir, exist_ok=True)
    res = {}

    for code, spec, key, with_comp, task in AGENTS:
        if with_comp and not _competitor_md(slug):
            res[code] = "нет данных конкурентов — пропуск"
            continue
        prompt = build_prompt(slug, spec, task, with_comp)
        open(os.path.join(PROMPTS_DIR, f"{slug}_{code}_prompt.md"), "w", encoding="utf-8").write(prompt)
        out = stub_output(slug, code, A) if stub else run_claude(prompt)[0]
        if not out:
            res[code] = "CLI недоступен — пропуск (дашборд соберётся без разбора)"
            continue
        v = verify_text(out, A, label=f"{slug}/{code}")
        if not v["pass"]:
            open(os.path.join(odir, f"{code}.REJECTED.md"), "w", encoding="utf-8").write(out)
            res[code] = f"БРАК: числа не из контракта ({v['total']-v['verified']}) — не вшито"
            continue
        open(os.path.join(odir, f"{code}.md"), "w", encoding="utf-8").write(out)
        A["analysis"][key] = out
        res[code] = f"OK: вшит ({v['verified']}/{v['total']} чисел)"

    with open(cpath, "w", encoding="utf-8") as fh:        # явный fsync: разбор гарантированно на диске
        json.dump(A, fh, ensure_ascii=False, indent=2)    # до того, как dash прочитает контракт
        fh.flush()
        os.fsync(fh.fileno())
    return res


def main(stub=False):
    print(f"=== run_agents: LLM-анализ поверх контрактов | режим={'STUB' if stub else 'Claude CLI'} ===\n")
    for slug in ORDER:
        r = run_for_dept(slug, stub=stub)
        print(f"[{slug}] " + " | ".join(f"{c}:{m}" for c, m in r.items()))
    print("\nРазбор вшит в out/<отдел>/analysis.json -> A['analysis']; дальше dash рисует секцию.")


if __name__ == "__main__":
    main(stub=("--stub" in sys.argv))
