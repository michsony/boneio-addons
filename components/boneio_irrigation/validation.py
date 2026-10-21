"""Installation validation also applies to YAML edited outside Studio."""
import datetime
import math
import re


def validate(c):
    def require(condition, message):
        if not condition: raise ValueError(message)
    def number(value, low=0, high=86400, integer=True):
        require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high and (not integer or int(value) == value), "Invalid number or duration")
    def date(value):
        value = str(value)
        require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), "Invalid date")
        datetime.date.fromisoformat(value)
    def schedule(value, inherit=True):
        require(value["mode"] in (("inherit",) if inherit else ()) + ("weekly", "interval", "odd", "even"), "Invalid schedule mode")
        number(value["days"], 0, 127); number(value["every"], 1, 365); date(value["anchor"])
    def cycle(value, inherit=False):
        number(value["seconds"], -1 if inherit else 0); number(value["soak"], -1 if inherit else 0)
    identifier = re.compile(r"^[A-Za-z_]\w*$", re.ASCII)
    require(c["version"] == 1 and c["name"].strip(), "Unsupported configuration version or empty name")
    for key, maximum in {"zones": 32, "pumps": 8, "programs": 16, "starts": 24, "queue": 128}.items(): number(c["capacity"][key], 0 if key == "pumps" else 1, maximum)
    require(0 < len(c["zones"]) <= c["capacity"]["zones"] and len(c["pumps"]) <= c["capacity"]["pumps"] and len(c["programs"]) <= c["capacity"]["programs"], "Capacity exceeded or no zones")
    require(c["capacity"]["queue"] >= len(c["zones"]), "Queue cannot hold a program")
    items = [c] + c["zones"] + c["pumps"] + c["programs"]
    require(all(identifier.fullmatch(v["id"]) for v in items) and len({v["id"] for v in items}) == len(items), "IDs must be unique identifiers")
    for group in (c["zones"], c["pumps"], c["programs"]): require(all(v["name"].strip() for v in group) and len({v["name"].strip() for v in group}) == len(group), "Names must be unique and nonempty")
    channels = [v["channel"] for v in c["zones"] + c["pumps"]]
    require(len(channels) == len(set(channels)) and all(re.fullmatch(r"(?:output|switch):[A-Za-z_]\w*", v, re.ASCII) for v in channels), "Duplicate or invalid physical channel")
    sensors = [c[k] for k in ("rainSensor", "emergencySensor", "temperatureSensor")] + [z["soilSensor"] for z in c["zones"]] + [p[k] for p in c["pumps"] for k in ("pressureSensor", "flowSensor")]
    require(all(not v or identifier.fullmatch(v) for v in sensors), "Invalid sensor reference")
    number(c["parallel"], 1, c["capacity"]["zones"]); number(c["maxWait"], 1); number(c["season"], 0, 300); number(c["rainHours"], 0, 720); number(c["sensorGrace"], 0, 300); number(c["temperatureMin"], -50, 80, False)
    zone_ids, pump_ids = {v["id"] for v in c["zones"]}, {v["id"] for v in c["pumps"]}
    for z in c["zones"]:
        number(z["min"], 1); number(z["max"], z["min"]); number(z["seconds"], z["min"], z["max"]); number(z["priority"], 0, 100); number(z["group"], 0, 32); number(z["order"], 0, c["capacity"]["zones"]); number(z["soilMax"], 0, 100, False)
        require(set(z["allowedPumps"]) <= pump_ids and (not z["pump"] or z["pump"] in z["allowedPumps"]), "Incompatible pump assignment")
        require(c["parallel"] <= 1 or z["group"] > 0, "Parallel zones need explicit hydraulic groups")
        schedule(z["schedule"]); cycle(z["cycle"])
    for p in c["pumps"]:
        for key in ("startDelay", "stopDelay", "rest"): number(p[key])
        number(p["minRun"], 1); number(p["maxRun"], p["minRun"])
        require(p["startOrder"] in ("pump-first", "valve-first") and p["stopOrder"] in ("pump-first", "valve-first"), "Invalid hydraulic sequence")
        for key in ("pressureMin", "flowMin", "flowMax"): number(p[key], 0, 1e9, False)
        require(not p["pressureMin"] or p["pressureSensor"], "Pressure threshold requires a sensor")
        require(not (p["flowMin"] or p["flowMax"]) or p["flowSensor"], "Flow threshold requires a sensor")
        require(not p["flowMax"] or p["flowMax"] >= p["flowMin"], "Invalid flow thresholds")
    for p in c["programs"]:
        schedule(p["schedule"], False); cycle(p["cycle"]); number(p["season"], 0, 300); number(p["priority"], 0, 100)
        require(p["policy"] in ("queue", "skip") and len({v["zone"] for v in p["zones"]}) == len(p["zones"]), "Invalid policy or duplicate program zone")
        for z in p["zones"]: require(z["zone"] in zone_ids, "Unknown zone"); number(z["seconds"]); number(z["order"], 0, c["capacity"]["zones"])
        for i, start in enumerate(p["starts"]):
            require(i < c["capacity"]["starts"] or not start["enabled"], "Too many active starts")
            number(start["hour"], 0, 23); number(start["minute"], 0, 59); schedule(start["schedule"]); cycle(start["cycle"], True)
            require(len({z["zone"] for z in start["zones"]}) == len(start["zones"]), "Duplicate start zone")
            for z in start["zones"]: require(z["zone"] in zone_ids and z["member"] in (-1, 0, 1), "Invalid start override"); number(z["seconds"]); number(z["order"], -1, c["capacity"]["zones"])
    require(len(c["exclusions"]) <= 16, "Too many date exclusions")
    for value in c["exclusions"]: date(value)
