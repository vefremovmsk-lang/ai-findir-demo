# ECharts-паттерны AI-Findir (проверенные конфиги)

Все примеры — Python-словари для `theme_findir.ech_init(div_id, option, height)`.
`ech_init` возвращает `(html_div, js_init)`; js собирай в один список и вставляй одним `<script>`.

## 1. Водопад (план-факт мост) — custom series

Стандартного waterfall в ECharts нет; stacked-bar с прозрачной базой ломается на смене знака.
Правильный способ — `type:'custom'` с renderItem (рисуем каждую ступень от y0 до y1 + пунктир-коннектор).
Данные: `[[i, y0, y1, kind, label], ...]`, kind ∈ st|neg|pos|en (старт/минус/плюс/итог).
Цвета: st=INDIGO, neg=CRIMSON, pos=GREEN, en=SLATE. JS-шаблон бери из dashboard2.py (блок «ГЕРОЙ»).
Проверка корректности: cumulative последней ступени == значение итогового столбца.

## 2. Калибровка «кому верить» — bar + scatter

Горизонтальные бары = сбываемость прогноза (цвет порогами: <35% CRIMSON, <60% AMBER, иначе GREEN),
ромбы (`type:'scatter', symbol:'diamond'`) = выполнение плана. Ось X в %, max 160.
Высота: `44 * len(managers) + 60`.

```python
{"name": "сбываемость прогноза", "type": "bar", "barWidth": 14,
 "data": [{"value": v, "itemStyle": {"color": c, "borderRadius": 4}} for v, c in zip(vals, colors)],
 "label": {"show": True, "position": "right", "formatter": "{c}%"}},
{"name": "выполнение плана", "type": "scatter", "symbol": "diamond", "symbolSize": 13,
 "data": attain, "itemStyle": {"color": SLATE}}
```

## 3. Воронка продаж — funnel с minSize

При реальных конверсиях (477 звонков → 16 КП → 3 договора) нижние ступени вырождаются в нити.
ОБЯЗАТЕЛЬНО `"minSize": "16%", "maxSize": "94%"` — иначе нечитаемо.
Малые кратные: по одной воронке на менеджера, грид из карточек, подпись конверсий под графиком.

## 4. «План-призрак» — кто недодал план

Два bar-ряда с `barGap: "-100%"`: широкий серый (план, barWidth 16, #e9e8e3) под узким цветным
(факт, barWidth 8, INDIGO). Читается мгновенно: насколько цветное короче серого — столько недодали.

## 5. Теплокарта сезонности

`type:'heatmap'`, x = кварталы (пометь текущий: «Q2 · сейчас»), y = продукты,
значения 0/1/2 (вне сезона/слабая/сильная), visualMap скрытый
`inRange: {"color": ["#f2f1ed", AMBER, CRIMSON]}`, ячейки с белой рамкой 2px + borderRadius 4.

## 6. Бары с подписями денег

Подписи значений — короткий формат через placeholder-приём:
```python
"label": {..., "formatter": "function"}   # placeholder
js = js.replace('"formatter": "function"',
                '"formatter": function(p){return (p.value/1e6).toFixed(2)+" млн";}')
```

## Общее

- grid: `{"left": 60-210, "right": 20-90, "top": 8-30, "bottom": 24-44}` — left зависит от длины подписей.
- splitLine цвет `#f0efeb`; оси без axisTick/axisLine у category.
- tooltip: `{"trigger": "axis", "axisPointer": {"type": "shadow"}}` для баров, `item` для custom/funnel.
- Высоту графика считай от числа строк (34–46px на строку + 40–60 на оси/легенду).
- В конце страницы один resize-обработчик на все .chart.
