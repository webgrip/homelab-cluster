from __future__ import annotations

from .tokens import BLUE, LOGS, PROM, kiosk_steps, target_met


def grid_pos(x, y, w, h):
    return {"h": h, "w": w, "x": x, "y": y}


def target(expr, ref="A", legend="", instant=False, fmt=None):
    t = {"refId": ref, "expr": expr, "datasource": PROM}
    if legend:
        t["legendFormat"] = legend
    if instant:
        t["instant"] = True
        t["range"] = False
    if fmt:
        t["format"] = fmt
    return t


def logs_stats(expr, ref="A", legend=""):
    t = {"refId": ref, "expr": expr, "queryType": "stats", "datasource": LOGS}
    if legend:
        t["legendFormat"] = legend
    return t


def logs_range(expr, ref="A", legend=""):
    t = {"refId": ref, "expr": expr, "queryType": "statsRange", "datasource": LOGS}
    if legend:
        t["legendFormat"] = legend
    return t


def sql(datasource, raw, ref="A", fmt="table"):
    return {"refId": ref, "datasource": datasource, "editorMode": "code", "format": fmt,
            "rawQuery": True, "rawSql": " ".join(raw.split())}


def value_map(**texts):
    return [{"type": "value", "options": {k: v if isinstance(v, dict) else {"text": v} for k, v in texts.items()}}]


def _datasource(targets):
    return (targets or [{}])[0].get("datasource", PROM)


def stat(title, expr, x=0, y=0, w=0, h=0, *, unit=None, desc="", thresholds=None, mappings=None, decimals=None,
         spark=False, color_mode="value", fixed_color=None, no_value="no data", targets=None, calcs="lastNotNull",
         value_size=None, links=None, text_mode="auto", fields=""):
    defaults = {"noValue": no_value}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if thresholds:
        defaults["thresholds"] = thresholds
        defaults["color"] = {"mode": "thresholds"}
    else:
        defaults["color"] = {"mode": "fixed", "fixedColor": fixed_color or "text"}
    if mappings:
        defaults["mappings"] = mappings
    if links:
        defaults["links"] = links
    options = {"reduceOptions": {"calcs": [calcs], "fields": fields, "values": False},
               "orientation": "auto", "textMode": text_mode, "wideLayout": True,
               "colorMode": color_mode, "graphMode": "area" if spark else "none", "justifyMode": "center"}
    if value_size:
        options["text"] = {"valueSize": value_size}
    targets = targets or [target(expr, instant=not spark)]
    return {
        "type": "stat", "title": title, "description": desc,
        "gridPos": grid_pos(x, y, w, h), "datasource": _datasource(targets),
        "options": options,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "targets": targets,
    }


def timeseries(title, targets, x=0, y=0, w=0, h=0, *, unit="short", desc="", overrides=None, thresholds=None,
               draw="line", legend_mode="list", legend_calcs=None, stack=False, decimals=None, log=False,
               min_zero=True, fill=0, bars_percent=False):
    custom = {"lineWidth": 2, "fillOpacity": fill, "showPoints": "never", "pointSize": 6,
              "drawStyle": draw, "lineInterpolation": "linear", "spanNulls": False}
    if min_zero:
        custom["axisSoftMin"] = 0
    if draw == "points":
        custom.update({"showPoints": "always", "lineWidth": 0, "pointSize": 7})
    if draw == "bars":
        custom.update({"fillOpacity": 80, "lineWidth": 0})
    if stack:
        custom["stacking"] = {"mode": "percent" if bars_percent else "normal", "group": "A"}
        custom["fillOpacity"] = max(custom["fillOpacity"], 55)
        custom["lineWidth"] = 0
    if log:
        custom["scaleDistribution"] = {"type": "log", "log": 10}
    if thresholds:
        custom["thresholdsStyle"] = {"mode": "line"}
    defaults = {"unit": unit, "custom": custom, "color": {"mode": "palette-classic"}}
    if decimals is not None:
        defaults["decimals"] = decimals
    if thresholds:
        defaults["thresholds"] = thresholds
    legend = {"displayMode": legend_mode, "placement": "bottom", "showLegend": legend_mode != "hidden"}
    if legend_calcs:
        legend["calcs"] = legend_calcs
    return {
        "type": "timeseries", "title": title, "description": desc,
        "gridPos": grid_pos(x, y, w, h), "datasource": _datasource(targets),
        "options": {"legend": legend, "tooltip": {"mode": "multi", "sort": "desc"}},
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "targets": targets,
    }


def color_overrides(names):
    return [{"matcher": {"id": "byName", "options": n},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
            for n, c in names]


def table(title, targets, x=0, y=0, w=0, h=0, *, desc="", rename=None, order=None, hide=None, overrides=None,
          sort_field=None, sort_desc=True, extra_transforms=None, no_value=None, font_size=None, cell_height="sm",
          merge=True):
    transforms = []
    if len(targets) > 1 and merge:
        transforms.append({"id": "merge", "options": {}})
    org = {"excludeByName": {"Time": True}, "renameByName": rename or {}, "indexByName": {}}
    for hname in hide or []:
        org["excludeByName"][hname] = True
    if order:
        org["indexByName"] = {n: i for i, n in enumerate(order)}
    transforms.append({"id": "organize", "options": org})
    transforms.extend(extra_transforms or [])
    if sort_field:
        transforms.append({"id": "sortBy", "options": {"sort": [{"field": sort_field, "desc": sort_desc}]}})
    options = {"showHeader": True, "cellHeight": cell_height, "footer": {"show": False}}
    if font_size:
        options["fontSize"] = font_size
    defaults = {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "filterable": False},
                "color": {"mode": "fixed", "fixedColor": "text"}}
    if no_value:
        defaults["noValue"] = no_value
    return {
        "type": "table", "title": title, "description": desc,
        "gridPos": grid_pos(x, y, w, h), "datasource": _datasource(targets),
        "options": options,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "transformations": transforms,
        "targets": targets,
    }


def col(name, *, unit=None, thresholds=None, bg=False, colour_text=False, gauge=False, mappings=None, width=None,
        decimals=None, gauge_max=None, hidden=False, links=None):
    props = []
    if unit:
        props.append({"id": "unit", "value": unit})
    if decimals is not None:
        props.append({"id": "decimals", "value": decimals})
    if thresholds:
        props.append({"id": "thresholds", "value": thresholds})
        props.append({"id": "color", "value": {"mode": "thresholds"}})
    if bg:
        props.append({"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}})
    if colour_text:
        props.append({"id": "custom.cellOptions", "value": {"type": "color-text"}})
    if gauge:
        props.append({"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}})
        props.append({"id": "color", "value": {"mode": "fixed", "fixedColor": BLUE}})
        props.append({"id": "min", "value": 0})
        if gauge_max is not None:
            props.append({"id": "max", "value": gauge_max})
    if mappings:
        props.append({"id": "mappings", "value": mappings})
    if width:
        props.append({"id": "custom.width", "value": width})
    if hidden:
        props.append({"id": "custom.hidden", "value": True})
    if links:
        props.append({"id": "links", "value": links})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def bullet(title, targets, x=0, y=0, w=0, h=0, *, goal, maximum, unit=None, higher_is_better=True, desc="",
           no_value="no data", decimals=None, overrides=None, value_size=22):
    defaults = {"min": 0, "max": maximum, "color": {"mode": "thresholds"},
                "thresholds": target_met(goal, higher_is_better=higher_is_better), "noValue": no_value}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "type": "bargauge", "title": title, "description": desc, "datasource": _datasource(targets),
        "gridPos": grid_pos(x, y, w, h),
        "options": {"orientation": "horizontal", "displayMode": "basic", "valueMode": "text",
                    "namePlacement": "left", "showUnfilled": True, "sizing": "auto",
                    "minVizWidth": 8, "minVizHeight": 12, "maxVizHeight": 28,
                    "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
                    "text": {"titleSize": 13, "valueSize": value_size}},
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "targets": targets,
    }


def bars(title, targets, x=0, y=0, w=0, h=0, *, unit=None, desc="", thresholds=None, no_value="no data",
         decimals=None, maximum=None, value_size=18, fixed_color=None):
    defaults = {"min": 0, "noValue": no_value}
    if maximum is not None:
        defaults["max"] = maximum
    if thresholds:
        defaults["thresholds"] = thresholds
        defaults["color"] = {"mode": "thresholds"}
    else:
        defaults["color"] = {"mode": "fixed", "fixedColor": fixed_color or BLUE}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "type": "bargauge", "title": title, "description": desc, "datasource": _datasource(targets),
        "gridPos": grid_pos(x, y, w, h),
        "options": {"orientation": "horizontal", "displayMode": "basic", "valueMode": "text",
                    "namePlacement": "left", "showUnfilled": True, "sizing": "auto",
                    "minVizWidth": 8, "minVizHeight": 12, "maxVizHeight": 26,
                    "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
                    "text": {"titleSize": 13, "valueSize": value_size}},
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "targets": targets,
    }


def state_timeline(title, targets, x=0, y=0, w=0, h=0, *, thresholds=None, mappings=None, desc="",
                   show_value="always", row_height=0.9, links=None, time_from=None):
    defaults = {"decimals": 0, "custom": {"lineWidth": 0, "fillOpacity": 90}, "color": {"mode": "thresholds"},
                "thresholds": thresholds or kiosk_steps()}
    if mappings:
        defaults["mappings"] = mappings
    if links:
        defaults["links"] = links
    panel = {
        "type": "state-timeline", "title": title, "description": desc, "datasource": _datasource(targets),
        "gridPos": grid_pos(x, y, w, h),
        "options": {"showValue": show_value, "rowHeight": row_height, "mergeValues": True,
                    "legend": {"showLegend": False}, "tooltip": {"mode": "single"}},
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "targets": targets,
    }
    if time_from:
        panel["timeFrom"] = time_from
        panel["hideTimeOverride"] = True
    return panel


def heatmap(title, targets, x=0, y=0, w=0, h=0, *, unit="s", desc=""):
    return {
        "type": "heatmap", "title": title, "description": desc, "datasource": _datasource(targets),
        "gridPos": grid_pos(x, y, w, h),
        "options": {"calculate": False, "cellGap": 1, "color": {"mode": "scheme", "scheme": "Blues", "steps": 64,
                                                                   "exponent": 0.5, "fill": BLUE, "reverse": False},
                    "yAxis": {"unit": unit, "axisPlacement": "left"}, "legend": {"show": False},
                    "tooltip": {"mode": "single", "yHistogram": True}, "filterValues": {"le": 1e-9},
                    "rowsFrame": {"layout": "auto"}},
        "fieldConfig": {"defaults": {}, "overrides": []},
        "targets": targets,
    }


def row(title, y, collapsed=False, panels=None):
    return {"type": "row", "title": title, "collapsed": collapsed,
            "gridPos": grid_pos(0, y, 24, 1), "panels": panels or []}


def text(title, md, x=0, y=0, w=0, h=0, *, transparent=False):
    panel = {"type": "text", "title": title, "gridPos": grid_pos(x, y, w, h),
             "options": {"mode": "markdown", "content": md}}
    if transparent:
        panel["transparent"] = True
    return panel


def var_query(name, label, query, *, sort=1, include_all=False, multi=False, hidden=False, all_value=".*"):
    v = {"name": name, "label": label, "type": "query", "datasource": PROM, "query": query,
         "refresh": 2, "sort": sort, "includeAll": include_all, "multi": multi,
         "current": {"text": "All", "value": "$__all"} if include_all else {}, "options": []}
    if include_all:
        v["allValue"] = all_value
    if hidden:
        v["hide"] = 2
    return v


def var_constant(name, value):
    return {"name": name, "type": "constant", "query": value, "hide": 2,
            "current": {"text": value, "value": value}, "options": []}
