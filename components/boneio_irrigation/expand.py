"""Expand installation data into native ESPHome components at build time.

No network, Studio service or runtime interpreter is used by this module.
The immutable blueprint and scheduler travel together in the user's Git release.
"""
import copy
import datetime
import json
import re
from pathlib import Path

BLUEPRINT = json.loads(Path(__file__).with_name("blueprint.json").read_text(encoding="utf8"))


def signature(text):
    value = 2166136261
    for char in text:
        value = ((value ^ ord(char)) * 16777619) & 0xFFFFFFFF
    return value


def civil_day(text):
    return (datetime.date.fromisoformat(str(text)) - datetime.date(1970, 1, 1)).days


def settings(c):
    z, m, p, s = (c["capacity"][k] for k in ("zones", "pumps", "programs", "starts"))
    zone = lambda i, f=0: 24 + i * 18 + f
    pump = lambda i, f=0: 24 + z * 18 + i * 12 + f
    program = lambda i, f=0: 24 + z * 18 + m * 12 + i * 12 + f
    member = lambda a, b, f=0: program(p) + (a * z + b) * 4 + f
    slot = lambda a, b, f=0: member(p, 0) + (a * s + b) * 10 + f
    over = lambda a, b, d, f=0: slot(p, 0) + ((a * s + b) * z + d) * 3 + f
    allow = lambda a, b: over(p, 0, 0) + a * m + b
    v = [0] * (allow(z, 0) + 16)
    def put(index, values):
        v[index:index + len(values)] = values
    def mode(schedule):
        return {"weekly": 0, "interval": 1, "odd": 2, "even": 3, "inherit": -1}[schedule["mode"]]
    put(0, [int(c["enabled"]), int(c["automatic"]), c["season"], 0, c["maxWait"], c["parallel"], c["rainHours"], c["sensorGrace"], int(bool(c["rainSensor"])), int(bool(c["emergencySensor"])), int(bool(c["temperatureSensor"])), c["temperatureMin"], len(c["zones"]), len(c["pumps"]), len(c["programs"]), len(c["exclusions"])])
    for i, date in enumerate(c["exclusions"]): v[allow(z, 0) + i] = civil_day(date)
    for i, item in enumerate(c["zones"]):
        sch = item["schedule"]
        pi = next((j for j, pump in enumerate(c["pumps"]) if pump["id"] == item["pump"]), -1)
        put(zone(i), [int(item["enabled"]), item["seconds"], item["min"], item["max"], pi, item["priority"], item["group"], int(bool(item["soilSensor"])), mode(sch), sch["days"], sch["every"], civil_day(sch["anchor"]), item["cycle"]["seconds"], item["cycle"]["soak"], item["order"], 1, item["soilMax"], 0])
        for j, pump_item in enumerate(c["pumps"]): v[allow(i, j)] = int(pump_item["id"] in item["allowedPumps"])
    for i, item in enumerate(c["pumps"]):
        put(pump(i), [int(item["enabled"]), item["startDelay"], item["stopDelay"], int(item["startOrder"] == "pump-first"), int(item["stopOrder"] == "valve-first"), item["minRun"], item["rest"], item["maxRun"], int(item["service"]), item["pressureMin"], item["flowMin"], item["flowMax"]])
    for i, item in enumerate(c["programs"]):
        sch = item["schedule"]
        put(program(i), [int(item["enabled"]), mode(sch), sch["days"], sch["every"], civil_day(sch["anchor"]), item["season"], item["priority"], int(item["policy"] == "skip"), item["cycle"]["seconds"], item["cycle"]["soak"], 1, 0])
        for j, zone_item in enumerate(c["zones"]):
            entry = next((v for v in item["zones"] if v["zone"] == zone_item["id"]), {})
            put(member(i, j), [int(entry.get("enabled", False)), entry.get("seconds", 0), entry.get("order", j), 0])
        for k in range(s):
            start = item["starts"][k] if k < len(item["starts"]) else None
            sch = start["schedule"] if start else {"mode": "inherit", "days": 127, "every": 1, "anchor": "2026-01-01"}
            cycle = start["cycle"] if start else {"seconds": -1, "soak": -1}
            put(slot(i, k), [int(start["enabled"]) if start else 0, start["hour"] if start else 5, start["minute"] if start else 30, mode(sch), sch["days"], sch["every"], civil_day(sch["anchor"]), cycle["seconds"], cycle["soak"], 0])
            for j, zone_item in enumerate(c["zones"]):
                entry = next((v for v in start["zones"] if v["zone"] == zone_item["id"]), {}) if start else {}
                put(over(i, k, j), [entry.get("member", -1), entry.get("seconds", 0), entry.get("order", -1)])
    return v


def driver(c, item):
    kind, name = item["channel"].split(":", 1)
    return name if kind == "switch" else f'{c["id"]}_driver_{item["id"]}'


def bootstrap(c, values, kernel_type):
    cid, cap = c["id"], c["capacity"]
    zd, pd = [driver(c, v) for v in c["zones"]], [driver(c, v) for v in c["pumps"]]
    cut = "\n".join(f"id({d}).turn_off();" for d in pd + zd)
    sig_data = [1, cid, {key: cap[key] for key in ("zones", "pumps", "programs", "starts", "queue")}, [z["id"] for z in c["zones"]], [p["id"] for p in c["pumps"]], [p["id"] for p in c["programs"]]]
    sig = signature(json.dumps(sig_data, separators=(",", ":"), ensure_ascii=False))
    dispatch = []
    for i, item in enumerate(c["zones"]):
        pump_switch = "".join(f"case {j}:driver=id({d});break;" for j, d in enumerate(pd))
        dispatch.append(f'case {i}: {{auto *executor=id({cid}_executor_{item["id"]}); executor->set_auto_advance(false);executor->set_queue_enable(false);executor->set_multiplier(1.0f);int pump=int(id({cid})->z({i},4)); esphome::switch_::Switch *driver=id({cid}_no_pump);switch(pump){{{pump_switch}}}executor->configure_valve_pump_switch(0,driver);float start=pump>=0?id({cid})->m(pump,1):0,stop=pump>=0?id({cid})->m(pump,2):0;if(pump>=0&&id({cid})->m(pump,3))executor->set_valve_start_delay(start);else executor->set_pump_start_delay(start);if(pump>=0&&id({cid})->m(pump,4))executor->set_pump_stop_delay(stop);else executor->set_valve_stop_delay(stop);executor->start_single_valve(0,seconds);break;}}')
    sensor_cases = []
    for kind, key in enumerate(("rainSensor", "emergencySensor", "temperatureSensor")):
        sid = c[key]
        expression = f'id({sid}).has_state() ? float(id({sid}).state) : NAN' if sid and kind < 2 else f'id({sid}).state' if sid else "0.0f" if kind < 2 else "NAN"
        sensor_cases.append(f"case {kind}:return {expression};")
    for kind, field, items in ((3, "soilSensor", c["zones"]), (4, "pressureSensor", c["pumps"]), (5, "flowSensor", c["pumps"])):
        cases = "".join(f'case {i}:return ' + (f'id({item[field]}).state' if item[field] else 'NAN') + ';' for i, item in enumerate(items))
        sensor_cases.append(f"case {kind}:switch(index){{{cases}default:return NAN;}}")
    stop = "".join(f'case {i}:id({cid}_executor_{z["id"]}).shutdown(true);break;' for i, z in enumerate(c["zones"]))
    busy = "".join(f'case {i}:return id({cid}_executor_{z["id"]}).controller_state()!=esphome::sprinkler::IDLE;' for i, z in enumerate(c["zones"]))
    valve = "".join(f'case {i}:return id({d}).state;' for i, d in enumerate(zd))
    pump = "".join(f'case {i}:return id({d}).state;' for i, d in enumerate(pd))
    controllers = "\n".join(f'id({cid}_executor_{a["id"]}).add_controller(id({cid}_executor_{b["id"]}));' for a in c["zones"] for b in c["zones"] if a["id"] != b["id"])
    defaults = ",".join(str(v) for v in values)
    return f'''{cut}
using Runtime={kernel_type};
id({cid})=new Runtime();auto *r=id({cid});r->init({{{cap['zones']},{cap['pumps']},{cap['programs']},{cap['starts']}}},{sig}u);
static const float defaults[]={{{defaults}}};for(int i=0;i<{len(values)};i++)r->values[i]=defaults[i];
static auto preference=esphome::global_preferences->make_preference<Runtime::Snapshot>({signature(cid + '-irrigation-prefs')}u);
preference.load(&r->saved);r->restore();
r->hooks.start=[](int zone,uint32_t seconds){{switch(zone){{{''.join(dispatch)}}}}};
r->hooks.stop=[](int zone){{switch(zone){{{stop}}}}};
r->hooks.emergency=[](){{{cut}}};
r->hooks.busy=[](int zone)->int{{switch(zone){{{busy}}}return 0;}};
r->hooks.valve=[](int zone)->int{{switch(zone){{{valve}}}return 0;}};
r->hooks.pump=[](int pump)->int{{switch(pump){{{pump}}}return 0;}};
r->hooks.sensor=[](int kind,int index)->float{{switch(kind){{{''.join(sensor_cases)}}}return NAN;}};
r->hooks.commit=[]()->bool{{const auto &snapshot=id({cid})->snapshot();return preference.save(&snapshot)&&esphome::global_preferences->sync();}};
{controllers}'''


def expand_controller(c):
    cid, cap = c["id"], c["capacity"]
    values = settings(c)
    kernel_type = "boneio_irrigation::Engine<" + ",".join(str(v) for v in (cap["zones"], cap["pumps"], cap["programs"], cap["starts"], len(values), cap["queue"])) + ">"
    result = {}
    cases = lambda items: "".join(f'case {i}:return {{{json.dumps(v["name"], ensure_ascii=False)}}};' for i, v in enumerate(items))
    def render(value, item=None, index=0, kind=None):
        if isinstance(value, list): return [render(v, item, index, kind) for v in value]
        if isinstance(value, dict): return {k: render(v, item, index, kind) for k, v in value.items()}
        if not isinstance(value, str): return value
        for token, items in (("ZONE", c["zones"]), ("PUMP", c["pumps"]), ("PROGRAM", c["programs"])):
            value = value.replace(f'case 0:return {{"BIS_{token}_NAME"}};', cases(items))
        if item and kind in ("zone", "pump"):
            value = value.replace(f"bis_controller_token_driver_bis_{kind}_token", driver(c, item))
        value = value.replace("bis_controller_token", cid).replace("BIS_CONTROLLER_NAME", c["name"])
        if item:
            value = value.replace(f"bis_{kind}_token", item["id"]).replace(f"BIS_{kind.upper()}_NAME", item["name"])
            if kind == "zone":
                for text in ("zoneSeconds[0]", "active[0]", "zone_requested(0)", "manual_zone(0)", "cancel_zone(0)", "->z(0,", "->z(0)"):
                    value = value.replace(text, text.replace("0", str(index), 1))
                value = value.replace("output:out_01", item["channel"])
                value = value.replace("out_01", item["channel"].split(":", 1)[1])
                value = value.replace("z(0,4)", f"z({index},4)")
            elif kind == "pump": value = value.replace("pumpSeconds[0]", f"pumpSeconds[{index}]").replace("out_02", item["channel"].split(":", 1)[1])
            elif kind == "program":
                for text in ("enqueue_program(0)", "cancel_program(0)", "->p(0,", "l.member(0,"):
                    value = value.replace(text, text.replace("0", str(index), 1))
        value = value.replace("i<1;", f'i<{len(c["zones"])};').replace("z<1;", f'z<{len(c["zones"])};')
        return value
    for section, entries in BLUEPRINT.items():
        target = result.setdefault(section, [])
        for entry in entries:
            original_id = entry.get("id", entry.get("trigger_id", ""))
            kind = next((k for k in ("zone", "pump", "program") if f"bis_{k}_token" in original_id), None)
            for index, item in enumerate(c[kind + "s"] if kind else [None]):
                node = render(copy.deepcopy(entry), item, index, kind)
                eid = node.get("id", node.get("trigger_id", ""))
                suffix = eid.removeprefix(cid + "_")
                if section == "globals": node["type"] = kernel_type + "*"
                if section == "time": node["timezone"] = c["timezone"]
                if section == "esphome.on_boot": node["then"] = [{"lambda": bootstrap(c, values, kernel_type)}]
                if kind == "zone" and section == "switch" and "_driver_" in original_id:
                    if item["channel"].startswith("switch:"): continue
                if kind == "pump" and section == "switch" and "_driver_" in original_id:
                    if item["channel"].startswith("switch:"): continue
                if kind == "zone" and section == "sprinkler":
                    node["valves"][0]["valve_switch_id"] = driver(c, item)
                if kind == "zone" and section == "switch" and "_manual_" in eid: node["icon"] = item["icon"]
                if kind == "program" and section == "button" and "_run_" in eid: node["icon"] = item["icon"]
                if section == "number" and suffix in ("zone_order", "member_order", "slot_order"): node["max_value"] = cap["zones"]
                if suffix == "parallel":
                    if c["parallel"] <= 1: continue
                    node["max_value"] = c["parallel"]
                if not c["pumps"] and (suffix.startswith("pump_") and suffix != "pump_context"): continue
                contexts = {"zone_context": [v["name"] for v in c["zones"]], "pump_context": [v["name"] for v in c["pumps"]], "program_context": [v["name"] for v in c["programs"]], "slot_context": [str(i + 1) for i in range(cap["starts"])]}
                if section == "select" and suffix in contexts:
                    node["options"] = contexts[suffix] or ["Brak"]
                    node["initial_option"] = node["options"][0]
                if section == "select" and suffix == "zone_pump":
                    node["options"] = ["Bez pompy"] + [v["name"] for v in c["pumps"]]
                    context = f'auto *r=id({cid});if(!r)return;int zi=id({cid}_zone_context).active_index().value_or(0);'
                    getter = context.replace('if(!r)return;', 'if(!r)return {};')
                    node["lambda"] = getter + 'int value=int(r->get(r->l.zone(zi,4)))+1;switch(value){' + ''.join(f'case {i}:return {{{json.dumps(v, ensure_ascii=False)}}};' for i, v in enumerate(node["options"])) + '}return {};'
                    node["set_action"] = [{"lambda": context + ''.join(f'if(x=={json.dumps(v, ensure_ascii=False)}){{r->set(r->l.zone(zi,4),{i-1});}}' for i, v in enumerate(node["options"]))}]
                target.append(node)
    return result
