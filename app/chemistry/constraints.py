"""Check a lab requirement against recorded fields; an empty field is not a negative result."""
import re

NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
SEPARATOR = r"(?:-|–|—|~|～|至|到|to|→)"
MISSING = {"", "-", "—", "n/a", "na", "unknown", "not reported", "未记录", "未提供", "未知", "未说明", "未提及", "未披露", "not specified", "not disclosed", "not available", "n.d."}
ABSENT = {
    "catalyst": {"无催化剂", "不使用催化剂", "no catalyst", "catalyst-free"},
    "solvent": {"无溶剂", "不使用溶剂", "solvent-free", "no solvent", "neat"},
    "workup": {"无后处理", "no workup", "no work-up"},
}
WORKUP = re.compile(r"萃取|过滤|重结晶|洗涤|淬灭|纯化|干燥|浓缩|蒸馏|\b(?:wash|filter|extract|quench|purif|recrystalli|concentrat|distill|acidifi|neutraliz|dried)\w*\b", re.I)


def interval(text, unit):
    """Parse a value or range in one unit; refuse unrelated numbers or mixed units."""
    text = str(text or "").strip().replace("−", "-")
    match = re.fullmatch(rf"({NUMBER})\s*(?:(?:{unit})?\s*{SEPARATOR}\s*({NUMBER})\s*)?(?:{unit})", text, re.I)
    if match:
        values = [float(x) for x in match.groups() if x is not None]
        return min(values), max(values)
    return None


def yield_range(text):
    spread = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[%％]?\s*±\s*(\d+(?:\.\d+)?)\s*[%％]", str(text or "").strip())
    if spread:
        center, deviation = map(float, spread.groups())
        result = round(center - deviation, 8), round(center + deviation, 8)
    else:
        result = interval(text, r"[%％]?")
    return result if result and 0 <= result[0] <= result[1] <= 100 else None


def peak_temperature(text):
    result = interval(text, r"(?:°\s*C|℃|摄氏度|C)")
    return result[1] if result else None


def peak_hours(text):
    for unit, factor in [(r"(?:h|hr|hrs|hours?|小时)", 1), (r"(?:min|mins|minutes?|分钟)", 1/60),
                         (r"(?:d|days?|天)", 24)]:
        result = interval(text, unit)
        if result and result[0] >= 0:
            return result[1] * factor
    return None


def present(raw, key):
    s = str(raw or "").strip().casefold()
    if key == "workup":
        # Imported 'other' also contains unrelated pH, atmosphere and procedure notes.
        tagged = re.search(r"(?:^|;\s*)workup:\s*([^;]+)", s)
        if tagged:
            return present(tagged[1], "workup_value")
    if s in MISSING:
        return None
    if s in {"none", "无", "不使用"} | ABSENT.get(key, ABSENT["workup"]):
        return False
    if key == "workup":
        return True if WORKUP.search(s) else None
    return True


def evaluate_constraints(item, filters):
    conditions = item.get("conditions_summary") or []
    checks = []

    def add(key, request, record, decision):
        checks.append({"key": key, "requirement": request, "record": record or "未记录",
                       "status": "unknown" if decision is None else ("met" if decision else "conflict")})

    def records(field):
        return "；".join(f"步骤 {c.get('step') or i}：{c.get(field) or '未记录'}"
                        for i, c in enumerate(conditions, 1))

    def all_known(values):
        reported_steps = item.get("steps") or 1
        distinct = {c.get("step") or i for i, c in enumerate(conditions, 1)}
        return bool(values) and None not in values and len(distinct) >= reported_steps

    # A reported yield range must lie entirely above the minimum to confirm it.
    ys = yield_range(item.get("yield_"))
    limit = filters.get("min_yield")
    if limit is not None:
        decision = None if ys is None or ys[0] < limit <= ys[1] else ys[0] >= limit
        add("min_yield", f"收率 ≥ {limit:g}%", item.get("yield_"), decision)
    steps = item.get("steps")
    limit = filters.get("max_steps")
    if limit is not None:
        add("max_steps", f"步骤 ≤ {limit} 步", f"{steps} 步" if steps else None,
            steps <= limit if steps else None)

    summary = {"yield_val": sum(ys)/2 if ys else None, "steps_val": steps}
    # A known breach is conclusive even when another condition row is missing.
    for key, field, name, unit, parse, output in [
        ("max_temperature", "temperature", "最高温度", "°C", peak_temperature, "temp_val"),
        ("max_time_hours", "time", "最长单段时间", "h", peak_hours, "time_val"),
    ]:
        values = [parse(part) for c in conditions
                  for part in re.split(r"[;；→]", str(c.get(field) or ""))]
        peak = max((v for v in values if v is not None), default=None)
        summary[output] = peak
        limit = filters.get(key)
        if limit is not None:
            decision = False if peak is not None and peak > limit else (True if all_known(values) else None)
            add(key, f"{name} ≤ {limit:g} {unit}", records(field), decision)

    for key, field, label in [("catalyst", "catalysts", "催化剂"), ("solvent", "solvents", "溶剂"),
                              ("workup", "other", "后处理")]:
        raw = [c.get(field) for c in conditions]
        states = [present(value, key) for value in raw]
        state = True if True in states else (False if all_known(states) else None)
        summary[key + "_val"] = state
        pref = filters.get(key)
        if pref in ("with", "without"):
            add(key, ("需要" if pref == "with" else "不使用") + label, records(field),
                None if state is None else state == (pref == "with"))
        if key == "workup":
            continue
        summary[key + "_names"] = "; ".join(v for v, status in zip(raw, states) if status is True)
        keyword = (filters.get(key + "_name") or "").strip()
        if keyword:
            found = any(keyword.casefold() in v.casefold() for v, status in zip(raw, states) if status is True)
            add(key + "_name", f"{label}含「{keyword}」", records(field),
                True if found else (False if all_known(states) else None))

    matched = sum(row["status"] == "met" for row in checks)
    return {**summary, "checks": checks, "matched_conditions": matched, "exact": bool(checks) and matched == len(checks)}
