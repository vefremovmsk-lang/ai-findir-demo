# -*- coding: utf-8 -*-
"""
competitor_scan — узел 04, СБОР ФАКТОВ о конкурентах через Firecrawl (боевой режим).

Принцип контура: инструмент СОБИРАЕТ, ИИ-агент 04 АНАЛИЗИРУЕТ. Здесь два шага сбора:
  1) DISCOVERY  — app.search(запросы по направлению) → находим АКТИВНЫХ игроков рынка
                  (не фиксированный список). Фильтруем домены: убираем наш сайт, агрегаторы,
                  госреестры, соцсети. Оставляем top-N доменов.
  2) SCRAPE     — app.scrape(страница) каждого кандидата → сырой markdown + провенанс.
Дальше узел 04 (LLM) сам решает, кто из найденного реальный конкурент, и даёт сравнение
с нашей компанией (услуги/ценники/позиционирование/новые продукты + 3 отличия) → блок competitors.live.

Выход:
  competitors/<direction>/<host>__<page>.md  — сырой markdown (НЕ коммитится)
  competitors/<direction>/_scan.json         — манифест: запросы, найдено, статус, кредиты, дата

Запуск:
  python competitor_scan.py --dry-run                 # офлайн-стаб (без сети/кредитов) — проверка логики
  python competitor_scan.py --direction eco           # живой discovery+scrape (нужен .env)
  python competitor_scan.py --seeds                    # fallback: фиксированный список вместо поиска
  python competitor_scan.py --budget 25 --max-sites 6  # потолки расхода

Кредиты: search ≈ 1/запрос, scrape = 1/стр. Бюджет-гард останавливает прогон на потолке.
"""
import os
import re
import sys
import json
import argparse
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone

LAB = Path(__file__).resolve().parent

# ---- направления: поисковые запросы + (fallback) сиды ----
DIRECTIONS = {
    "eco": {
        "name": "Экология",
        "queries": [
            "экологический аудит предприятия услуги",
            "разработка ПНООЛР ОВОС СЗЗ проект нормативов",
            "экологическое сопровождение предприятий компания",
        ],
        "seeds": ["https://rusregister.ru/", "https://serconsrus.ru/services/ekologiya/",
                  "https://ecostandardgroup.ru/services/"],
    },
}

# домены, которые НЕ конкуренты: наш сайт, агрегаторы/каталоги, гос, соцсети, маркетплейсы
OUR_HOSTS = {"example.ru"}   # TODO: укажите домен(ы) вашей компании, чтобы исключить из выдачи
EXCLUDE_SUBSTR = ("wikipedia.", "rusprofile", "list-org", "zoon.", "yell.", "2gis.", "yandex.",
                  "google.", "youtube.", "vk.com", "t.me", "rbc.", "gov.ru", "consultant.ru",
                  "garant.ru", "avito.", "hh.ru", "spark-interfax", "audit-it.")


def host_of(url):
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def load_key():
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("[!] нет python-dotenv: pip install firecrawl-py python-dotenv"); raise
    for p in (LAB / ".env", LAB / "firecrawl_test" / ".env"):
        if p.exists():
            load_dotenv(p)
            if os.getenv("FIRECRAWL_API_KEY"):
                return os.getenv("FIRECRAWL_API_KEY"), str(p)
    return None, None


# ---- офлайн-заглушки для --dry-run ----
class StubDoc:
    def __init__(self, url):
        self.markdown = f"# Заглушка {url}\n\nУслуги: пример А, пример Б. Цена: по запросу. О компании: демо.\n"
        self.metadata = {"sourceURL": url, "statusCode": 200, "credits_used": 1}

def stub_search(query):
    base = re.sub(r"[^a-z]+", "", query.lower())[:6] or "demo"
    return [f"https://{base}-company.ru/", f"https://{base}-expert.ru/uslugi/",
            "https://rusprofile.ru/ignore", f"https://{base}-eco.ru/"]


def fc_search(app, query, dry):
    if dry:
        return stub_search(query), None
    try:
        resp = app.search(query, limit=6)
        # форма ответа SDK v2 может отличаться — разбираем мягко (+ диагностика снаружи)
        items = getattr(resp, "web", None) or getattr(resp, "data", None) or resp
        urls = []
        for it in (items or []):
            u = getattr(it, "url", None) or (it.get("url") if isinstance(it, dict) else None)
            if u:
                urls.append(u)
        return urls, (resp if not urls else None)   # вернём сырой resp для диагностики, если не распарсили
    except Exception as e:
        return [], repr(e)[:200]


def fc_scrape(app, url, dry):
    if dry:
        return StubDoc(url), None
    try:
        return app.scrape(url, formats=["markdown"]), None
    except Exception as e:
        return None, repr(e)[:200]


def meta_dict(doc):
    md = getattr(doc, "metadata", None)
    if md is None: return {}
    if isinstance(md, dict): return md
    if hasattr(md, "model_dump"):
        try: return md.model_dump()
        except Exception: pass
    try: return dict(vars(md))
    except Exception: return {}

def credits_of(doc):
    for k, v in meta_dict(doc).items():
        if "credit" in k.lower() and isinstance(v, (int, float)):
            return int(v)
    return 1

def status_of(doc):
    md = meta_dict(doc)
    for k in ("statusCode", "status_code", "status"):
        if md.get(k) is not None: return md[k]
    return None


def discover(app, direction, dry, budget, spent):
    """Поиск активных конкурентов → отфильтрованный список доменов (url-ы для скрапа)."""
    cfg = DIRECTIONS[direction]
    found, seen_hosts, diag_done = [], set(), False
    for q in cfg["queries"]:
        if spent[0] >= budget:
            print(f"[БЮДЖЕТ] потолок {budget} на discovery — стоп."); break
        urls, raw = fc_search(app, q, dry)
        spent[0] += 1                                   # search ≈ 1 кредит
        if raw is not None and not dry and not diag_done:
            print("     [диагностика] сырой ответ search:", type(raw).__name__, str(raw)[:200]); diag_done = True
        kept = 0
        for u in urls:
            h = host_of(u)
            if not h or h in seen_hosts or h in OUR_HOSTS:
                continue
            if any(s in h for s in EXCLUDE_SUBSTR):
                continue
            seen_hosts.add(h); found.append(u); kept += 1
        print(f"[search] «{q}» → {len(urls)} рез., оставлено новых доменов: {kept}")
    return found


def run(direction, dry, budget, max_sites, use_seeds):
    out_dir = LAB / "competitors" / direction
    out_dir.mkdir(parents=True, exist_ok=True)
    app = None
    if not dry:
        key, src = load_key()
        if not key:
            print("[STOP] FIRECRAWL_API_KEY не найден — положи .env или запусти --dry-run"); return 2
        from firecrawl import Firecrawl
        app = Firecrawl(api_key=key); print(f"[ok] ключ из {src}")

    spent = [0]
    print(f"=== competitor_scan: направление={direction} | режим={'DRY' if dry else 'LIVE'} | "
          f"бюджет={budget} | источник={'СИДЫ' if use_seeds else 'ПОИСК'} ===\n")

    if use_seeds:
        candidates = DIRECTIONS[direction]["seeds"]
    else:
        candidates = discover(app, direction, dry, budget, spent)
    candidates = candidates[:max_sites]
    print(f"\nкандидатов к скрапу (cap {max_sites}): {len(candidates)}")
    for u in candidates:
        print("   •", u)

    manifest = []
    for url in candidates:
        if spent[0] >= budget:
            print(f"[БЮДЖЕТ] потолок {budget} на scrape — стоп."); break
        doc, err = fc_scrape(app, url, dry)
        if err or doc is None:
            manifest.append({"url": url, "host": host_of(url), "ok": False, "error": err,
                             "status": None, "credits": 0, "chars": 0, "file": None})
            print(f"[ОШИБКА] {url}: {err}"); continue
        c = credits_of(doc); spent[0] += c
        md = doc.markdown or ""
        page = re.sub(r"[^a-z0-9]+", "_", url.split("//", 1)[-1].lower()).strip("_")[:40] or "root"
        fname = f"{host_of(url).replace('.','_')}__{page}.md"
        (out_dir / fname).write_text(md, encoding="utf-8")
        manifest.append({"url": url, "host": host_of(url), "ok": True, "error": None,
                         "status": status_of(doc), "credits": c, "chars": len(md), "file": fname})
        print(f"[scrape] {url}\n     статус={status_of(doc)} | кредитов={c} | символов={len(md)} -> {fname}")

    meta = {"direction": direction, "mode": "dry" if dry else "live",
            "source": "seeds" if use_seeds else "search",
            "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "credits_spent": spent[0], "budget": budget, "results": manifest}
    (out_dir / "_scan.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in manifest if r["ok"])
    print(f"\n--- ИТОГ: найдено {len(candidates)} | скрапнуто {ok} | кредитов {spent[0]}/{budget} ---")
    print(f"манифест -> {out_dir / '_scan.json'}")
    print("ДАЛЕЕ: узел 04 (LLM) фильтрует реальных конкурентов и сравнивает с нами (competitors.live).")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--direction", default="eco", choices=list(DIRECTIONS))
    ap.add_argument("--budget", type=int, default=25)
    ap.add_argument("--max-sites", type=int, default=6)
    ap.add_argument("--seeds", action="store_true", help="fallback: фиксированный список вместо поиска")
    a = ap.parse_args()
    return run(a.direction, a.dry_run, a.budget, a.max_sites, a.seeds)


if __name__ == "__main__":
    sys.exit(main())
