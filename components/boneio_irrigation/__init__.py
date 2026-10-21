"""BoneIO irrigation: installation data in YAML, reusable logic in Git."""
import importlib
import math
from esphome import automation, codegen as cg, config_validation as cv
from esphome.core import CORE
from esphome.yaml_util import make_data_base
from esphome.core.config import StartupTrigger, ShutdownTrigger
from .expand import expand_controller, settings
from .validation import validate

MULTI_CONF = True
AUTO_LOAD = ["time", "template", "switch", "sensor", "binary_sensor", "text_sensor", "number", "select", "button", "datetime", "output"]


def _module(section, node):
    if section == "time": return importlib.import_module("esphome.components.sntp.time")
    if node.get("platform") == "template": return importlib.import_module(f"esphome.components.template.{section}")
    if node.get("platform") == "output": return importlib.import_module("esphome.components.output.switch")
    return importlib.import_module(f"esphome.components.{section}")


def _validate(config):
    c = config["configuration"]
    try:
        validate(c)
        defaults = settings(c)
        if len(defaults) > 32768 or len(defaults) * 4 + c["capacity"]["programs"] * c["capacity"]["starts"] * 4 + 1024 > 60000: raise ValueError("Persistent configuration exceeds 60 kB")
        if not all(math.isfinite(v) for v in defaults): raise ValueError("Non-finite setting")
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise cv.Invalid(f"Invalid irrigation installation: {error}") from error
    expanded = expand_controller(c)
    def provenance(value):
        if isinstance(value, dict): value = {provenance(k): provenance(v) for k, v in value.items()}
        elif isinstance(value, list): value = [provenance(v) for v in value]
        return make_data_base(value, c["id"])
    expanded = provenance(expanded)
    native = {}
    CORE.loaded_integrations.update(("globals", "sprinkler", "script", "interval", "sntp"))
    CORE.loaded_platforms.add("time/sntp")
    for section, nodes in expanded.items():
        validated = []
        for node in nodes:
            if section.startswith("esphome."):
                trigger = StartupTrigger if section.endswith("on_boot") else ShutdownTrigger
                schema = automation.validate_automation({cv.GenerateID("trigger_id"): cv.declare_id(trigger), cv.Optional("priority", default=600.0): cv.float_})
                validated.extend(schema(node))
                continue
            module = _module(section, node)
            if node.get("platform"):
                CORE.loaded_integrations.add(node["platform"])
                CORE.loaded_platforms.add(f'{section}/{node["platform"]}')
            platform = node.get("platform")
            node = {k: v for k, v in node.items() if k != "platform"}
            value = module.CONFIG_SCHEMA(node)
            if section in ("script", "interval", "sprinkler"): validated.extend(value if isinstance(value, list) else [value])
            else:
                if platform: value["platform"] = platform
                validated.append(value)
        native[section] = validated
    config["native"] = native
    return config


CONFIG_SCHEMA = cv.All(cv.Schema({cv.Required("configuration"): dict}), _validate)


async def to_code(config):
    cg.add_global(cg.RawStatement('#include "esphome/components/boneio_irrigation/kernel.h"'))
    async def build_trigger(conf):
        trigger = cg.new_Pvariable(conf["trigger_id"], conf["priority"])
        await cg.register_component(trigger, conf)
        await automation.build_automation(trigger, [], conf)
    for section, nodes in config["native"].items():
        if section.startswith("esphome."):
            for conf in nodes:
                CORE.add_job(build_trigger, conf)
            continue
        # Expose validated native declarations to ESPHome's source manifest.
        # The original YAML remains compact; no generated declarations are written back.
        CORE.config.setdefault(section, []).extend(nodes)
        if section in ("script", "interval", "sprinkler"):
            CORE.add_job(importlib.import_module(f"esphome.components.{section}").to_code, nodes)
            continue
        for conf in nodes:
            module = _module(section, {"platform": "output" if section == "switch" and "output" in conf else "template" if section in ("switch", "number", "select", "sensor", "binary_sensor", "text_sensor", "button", "datetime") else ""})
            CORE.add_job(module.to_code, conf)
