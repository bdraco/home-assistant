"""Generate usb file."""
from __future__ import annotations

import json

from .model import Config, Integration

BASE = """
\"\"\"Automatically generated by hassfest.

To update, run python3 -m script.hassfest
\"\"\"

# fmt: off

USB = {}
""".strip()


def generate_and_validate(integrations: list[dict[str, str]]):
    """Validate and generate usb data."""
    match_list = []

    for domain in sorted(integrations):
        integration = integrations[domain]

        if not integration.manifest or not integration.config_flow:
            continue

        match_types = integration.manifest.get("usb", [])

        if not match_types:
            continue

        for entry in match_types:
            match_list.append({"domain": domain, **entry})

    return BASE.format(json.dumps(match_list, indent=4))


def validate(integrations: dict[str, Integration], config: Config):
    """Validate usb file."""
    usb_path = config.root / "homeassistant/generated/usb.py"
    config.cache["usb"] = content = generate_and_validate(integrations)

    if config.specific_integrations:
        return

    with open(str(usb_path)) as fp:
        current = fp.read().strip()
        if current != content:
            config.add_error(
                "usb",
                "File usb.py is not up to date. Run python3 -m script.hassfest",
                fixable=True,
            )
        return


def generate(integrations: dict[str, Integration], config: Config):
    """Generate usb file."""
    usb_path = config.root / "homeassistant/generated/usb.py"
    with open(str(usb_path), "w") as fp:
        fp.write(f"{config.cache['usb']}\n")
