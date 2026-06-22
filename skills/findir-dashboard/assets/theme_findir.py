# -*- coding: utf-8 -*-
"""
theme_findir — дизайн-система AI-Findir (Дашборд 2.0).

Направление (по frontend-design skill): «печатный финансовый отчёт, оживший
на экране». Georgia для заголовков (авторитет годового отчёта), системный
sans для текста, мономер для цифр. Один акцент — фирменный кримсон.
Сигнатура: герой = финрез, разложенный водопадом (тезис продукта:
«не просто число, а причины»). Всё офлайн: шрифты системные, ECharts вшит.
"""
import json

# --- токены ---
INK = "#15151a"
MUT = "#6e6e78"
PAPER = "#faf9f7"
CARD = "#ffffff"
LINE = "#e8e7e2"
CRIMSON = "#d12b3b"
AMBER = "#df9426"
GREEN = "#2e9e5b"
INDIGO = "#3b4cc0"
SLATE = "#3d4654"

DISPLAY = "Georgia,'Times New Roman',serif"
BODY = "'Segoe UI',system-ui,-apple-system,sans-serif"
MONO = "'Cascadia Mono','Consolas',monospace"

ECH_PALETTE = [INDIGO, CRIMSON, GREEN, AMBER, SLATE, "#8a93d8"]


def money(v):
    return f"{v:,.0f}".replace(",", " ") + " ₽" if isinstance(v, (int, float)) else "—"


def short(v):
    if not isinstance(v, (int, float)):
        return "—"
    a = abs(v)
    s = f"{v/1e6:.2f} млн" if a >= 1e6 else (f"{v/1e3:.0f} тыс" if a >= 1e3 else f"{v:.0f}")
    return ("+" if v > 0 else "") + s


def pct(v):
    return f"{v*100:.0f}%" if isinstance(v, (int, float)) else "—"


def esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def surname(full):
    return (full or "").split()[0] if full else ""


CSS = f"""
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--ink:{INK};--mut:{MUT};--paper:{PAPER};--card:{CARD};--line:{LINE};
--crimson:{CRIMSON};--amber:{AMBER};--green:{GREEN};--indigo:{INDIGO};--slate:{SLATE};
--display:{DISPLAY};--body:{BODY};--mono:{MONO}}}
html{{scroll-behavior:smooth}}
body{{font-family:var(--body);background:var(--paper);color:var(--ink);line-height:1.55;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 30px 70px}}

/* шапка */
.top{{display:flex;justify-content:space-between;align-items:flex-end;padding:26px 0 18px;border-bottom:2px solid var(--ink);margin-bottom:0}}
.brand{{font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)}}
.brand b{{color:var(--crimson)}}
.h1{{font-family:var(--display);font-size:30px;font-weight:700;letter-spacing:-.01em;margin-top:6px}}
.top-meta{{font-size:11.5px;color:var(--mut);text-align:right;font-family:var(--mono);line-height:1.7}}

/* навигация-повестка */
.nav{{position:sticky;top:0;z-index:50;background:color-mix(in srgb,var(--paper) 92%,transparent);
backdrop-filter:blur(6px);border-bottom:1px solid var(--line);margin:0 -30px;padding:8px 30px;
display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}}
.nav a{{font-size:11px;font-weight:600;color:var(--mut);text-decoration:none;padding:5px 10px;
border-radius:999px;white-space:nowrap;font-family:var(--mono)}}
.nav a:hover{{background:#efeeea;color:var(--ink)}}
.nav a.hot{{color:var(--crimson)}}

/* герой-тезис */
.hero2{{display:grid;grid-template-columns:330px 1fr;gap:0;border:1px solid var(--line);
border-radius:16px;background:var(--card);margin-top:24px;overflow:hidden;box-shadow:0 1px 3px rgba(20,20,26,.05)}}
.hero2 .left{{padding:26px 28px;border-right:1px solid var(--line);display:flex;flex-direction:column;justify-content:center}}
.hero2 .lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut);font-weight:700}}
.hero2 .big{{font-family:var(--display);font-size:46px;font-weight:700;color:var(--crimson);line-height:1.05;margin:8px 0 4px;letter-spacing:-.02em}}
.hero2 .sub{{font-size:13px;color:var(--mut)}}
.hero2 .kpis{{display:flex;gap:22px;margin-top:20px;padding-top:16px;border-top:1px solid var(--line)}}
.hero2 .kpis .k .v{{font-family:var(--mono);font-size:14.5px;font-weight:700;white-space:nowrap}}
.hero2 .kpis .k .l{{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}}
.hero2 .right{{padding:14px 18px 6px}}
.hero2 .right .cap{{font-size:11px;color:var(--mut);font-family:var(--mono);padding:4px 6px 0}}

/* секции */
.sec{{margin:40px 0}}
.eyebrow{{font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--crimson);font-family:var(--mono)}}
.sec h2{{font-family:var(--display);font-size:23px;font-weight:700;margin:6px 0 6px;letter-spacing:-.01em}}
.sec .lead{{font-size:13.5px;color:var(--mut);margin-bottom:18px;max-width:720px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px 24px;box-shadow:0 1px 2px rgba(20,20,26,.04)}}

/* алерты */
.alertband{{border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 1px 2px rgba(20,20,26,.04);margin-top:18px}}
.alert{{display:flex;gap:12px;align-items:flex-start;padding:12px 18px;border-bottom:1px solid #f1f0ec;font-size:13.5px;background:var(--card)}}
.alert:last-child{{border-bottom:none}}
.alert .atag{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;padding:3px 8px;border-radius:6px;flex:none;margin-top:1px;font-family:var(--mono)}}
.alert.critical{{border-left:4px solid var(--crimson)}}.alert.critical .atag{{background:#fbe9eb;color:var(--crimson)}}
.alert.warn{{border-left:4px solid var(--amber)}}.alert.warn .atag{{background:#fcf1e0;color:#9a6512}}
.alert.opportunity{{border-left:4px solid var(--green)}}.alert.opportunity .atag{{background:#e6f4ec;color:#1e6e40}}

/* срочно */
.urgent{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--crimson);border-radius:14px;padding:18px 24px;box-shadow:0 1px 2px rgba(20,20,26,.04)}}
.urgent h3{{font-family:var(--display);font-size:16px;color:var(--crimson);margin-bottom:8px}}
.uitem{{display:flex;gap:12px;font-size:14.5px;padding:8px 0;border-bottom:1px solid #f4f3ef}}
.uitem:last-child{{border-bottom:none}}
.uitem .n{{font-family:var(--mono);color:var(--crimson);font-weight:800;flex:none;width:18px}}

/* таблицы */
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);text-align:left;padding:8px 10px;border-bottom:2px solid var(--ink);font-family:var(--mono)}}
td{{padding:9px 10px;border-bottom:1px solid #f1f0ec;vertical-align:top}}
td.num{{text-align:right;font-family:var(--mono);white-space:nowrap}}
tr:last-child td{{border-bottom:none}}
.pill{{display:inline-block;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:600}}
.pill.r{{background:#fbe9eb;color:var(--crimson)}}.pill.a{{background:#fcf1e0;color:#9a6512}}.pill.g{{background:#e6f4ec;color:#1e6e40}}

/* SMART-контроль */
.scsum{{display:flex;gap:14px;align-items:center;margin-bottom:14px;font-size:14px;font-weight:600}}
.scscore{{font-family:var(--display);font-size:34px;font-weight:700;padding:4px 16px;border-radius:12px}}
.scscore.r{{background:#fbe9eb;color:var(--crimson)}}.scscore.a{{background:#fcf1e0;color:#9a6512}}.scscore.g{{background:#e6f4ec;color:#1e6e40}}
.scrow{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 16px;margin-bottom:10px}}
.schead{{display:flex;gap:10px;align-items:center;font-size:13px;flex-wrap:wrap}}
.scbadge{{font-family:var(--mono);font-weight:800;font-size:14px;padding:2px 9px;border-radius:8px}}
.scbadge.r{{background:#fbe9eb;color:var(--crimson)}}.scbadge.a{{background:#fcf1e0;color:#9a6512}}.scbadge.g{{background:#e6f4ec;color:#1e6e40}}
.misses{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
.miss{{font-size:11px;background:#f6f5f1;border:1px solid var(--line);border-radius:999px;padding:2px 10px;color:#7a4a12}}
.rwline{{margin-top:9px;font-size:12.5px;font-family:var(--mono);background:#f2f7f3;border-left:3px solid var(--green);border-radius:0 8px 8px 0;padding:8px 12px;line-height:1.6}}
.rwlab{{display:inline-block;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#1e6e40;margin-right:8px}}

/* ledger */
.ledsum{{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;gap:14px;margin-bottom:14px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px}}
.kpi .lbl{{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);font-weight:700;font-family:var(--mono)}}
.kpi .val{{font-family:var(--mono);font-size:19px;font-weight:700;margin-top:5px}}
.age{{display:inline-block;font-family:var(--mono);font-size:11px;font-weight:700;padding:2px 9px;border-radius:999px;white-space:nowrap}}
.age.n{{background:#f3f2ee;color:var(--mut)}}.age.a{{background:#fcf1e0;color:#9a6512}}
.age.r{{background:#fbe9eb;color:var(--crimson)}}.age.g{{background:#e6f4ec;color:#1e6e40}}

/* конкуренты */
.rivals{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}}
.rchip{{border:1px solid var(--line);border-radius:999px;padding:6px 13px;font-size:12px;background:var(--card)}}
.rchip .cnt{{color:var(--crimson);font-family:var(--mono);font-weight:700}}.rchip .nt{{color:var(--mut)}}
.poscols{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}}
.posbox{{border:1px solid var(--line);border-radius:12px;padding:14px 16px;font-size:13px;white-space:pre-line;line-height:1.65;background:var(--card)}}
.posbox.edge{{border-left:4px solid var(--green)}}.posbox.gap{{border-left:4px solid var(--amber)}}
.posbox h4{{font-family:var(--display);font-size:13px;margin-bottom:8px}}

/* радар */
.rcard{{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--card);margin-bottom:10px}}
.rcard.push{{border-left:4px solid var(--green)}}.rcard.gap{{border-left:4px solid var(--amber)}}
.rcard.wave{{border-left:4px solid var(--crimson)}}.rcard.stable{{border-left:4px solid var(--amber)}}
.rcard .rt{{font-size:13px;font-weight:700}}
.rcard .rd{{font-size:12px;color:var(--mut);margin-top:4px}}
.rcard .rdl{{font-family:var(--mono);font-size:12px;margin-top:6px}}
.radar2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}

/* конвейер */
.pipe td.pn{{font-family:var(--mono);font-weight:800;color:var(--indigo);width:24px}}
.pipe .bs{{font-size:11px;color:var(--mut);margin-top:3px}}
.pipe .ow{{display:inline-block;background:#eef0fb;color:var(--indigo);padding:2px 9px;border-radius:6px;font-size:11px;font-weight:700;white-space:nowrap}}
.pipe .dl{{font-family:var(--mono);font-size:12px;white-space:nowrap}}

.chart{{width:100%}}
.foot{{margin-top:50px;padding-top:16px;border-top:2px solid var(--ink);font-size:11px;color:var(--mut);font-family:var(--mono);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}}
@media (max-width:900px){{.hero2{{grid-template-columns:1fr}}.hero2 .left{{border-right:none;border-bottom:1px solid var(--line)}}
.radar2,.poscols,.ledsum{{grid-template-columns:1fr}}}}
@media (prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
"""

# базовая тема ECharts
ECH_THEME = {
    "color": ECH_PALETTE,
    "textStyle": {"fontFamily": "Cascadia Mono, Consolas, monospace", "color": SLATE},
    "axisLine": {"lineStyle": {"color": LINE}},
}

ECH_COMMON = {
    "textStyle": {"fontFamily": "Segoe UI, system-ui, sans-serif", "color": SLATE},
    "animationDuration": 700,
}


def ech_init(div_id, option, height=300):
    """Возвращает <div> + JS-инициализацию графика (тема вшита в option)."""
    opt = {**ECH_COMMON, **option}
    return (f'<div id="{div_id}" class="chart" style="height:{height}px"></div>',
            f"echarts.init(document.getElementById('{div_id}'),null,{{renderer:'canvas'}})"
            f".setOption({json.dumps(opt, ensure_ascii=False)});")
