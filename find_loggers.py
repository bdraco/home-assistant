from __future__ import annotations

import ast
from collections import namedtuple
from collections.abc import Generator
import distutils
import glob
import imp
import json
import os
import pathlib
import pkgutil
import pprint
import subprocess
import sys

import pkg_resources
import setuptools

LOGGER_NAMES = {
    "beautifulsoup4": "bs4",
}

Import = namedtuple("Import", ["module", "name", "alias", "level"])

component_dir = pathlib.Path("homeassistant/components")

# These are builtin or generate a lot of noise
NO_LOGGER_MODULES = {
    "attr",
    "pytest",
    "asyncstdlib",
    "protobuf",
    "jsonpickle",
    "natsort",
    "colour",
    "aioshutil",
    "pillow",
    "PIL",
    "typer",
    "url_normalize",
    "tests",
    "docker",
    "cpe",
    "git",
    "multidict",
    "pulsectl",
    "pyudev",
    "ruamel",
    "sentry_sdk",
    "supervisor",
    "enum_compat",
    "websocket_client",
    "pyjwt",
    "urllib3",
    "flask",
    "guppy",
    "pyprof2calltree",
    "pytest_runner",
    "requests_toolbelt",
    "lxml",
    "backoff",
    "humps",
    "jmespath",
    "numpy",
    "click_log",
    "debugpy",
    "bs4",
    "beautifulsoup4",
    "cattrs",
    "python_slugify",
    "asyncio_throttle",
    "justbackoff",
    "anyio",
    "httpcore",
    "h11",
    "sniffio",
    "sqlalchemy",
    "serial",
    "pyserial",
    "aioserial",
    "requests_toolbelt",
    "keyring",
    "keyring.alt",
    "defusedxml",
    "aiofiles",
    "pycryptodomex",
    "jwt",
    "pandas",
    "yaml",
    "rsa",
    "pycountry_convert",
    "pyparsing",
    "xmltodict",
    "cachetools",
    "tzlocal",
    "websockets",
    "requests_oauthlib",
    "markdown",
    "python_engineio",
    "python_socketio",
    "argcomplete",
    "iso8601",
    "bitarray",
    "simplejson",
    "colorlog",
    "msgpack",
    "aiocache",
    "dicttoxml",
    "websocket",
    "pyobjc_core",
    "pyobjc_framework_corebluetooth",
    "pyobjc_framework_libdispatch",
    "ratelimit",
    "python-singleton",
    "python_singleton",
    "httplib2",
    "future",
    "click-plugins",
    "click_plugins",
    "cached-property",
    "cached_property",
    "isodate",
    "platformdirs",
    "click",
    "python-dotenv",
    "python_dotenv",
    "voluptuous_serialize",
    "python-dateutil",
    "python_dateutil",
    "charset-normalizer",
    "charset_normalizer",
    "pytz",
    "vol",
    "six",
    "pydantic",
    "packaging",
    "certifi",
    "idna",
    "pycryptodome",
    "typing_extensions",
    "typing-extensions",
    "async-timeout",
    "slugify",
}


def get_python_library():

    # Get list of the loaded source modules on sys.path.
    modules = {
        module
        for _, module, package in list(pkgutil.iter_modules())
        if package is False
    }

    # Glob all the 'top_level.txt' files installed under site-packages.
    site_packages = glob.iglob(
        os.path.join(
            os.path.dirname(os.__file__) + "/site-packages", "*-info", "top_level.txt"
        )
    )

    # Read the files for the import names and remove them from the modules list.
    modules -= {open(txt).read().strip() for txt in site_packages}

    # Get the system packages.
    system_modules = set(sys.builtin_module_names)

    # Get the just the top-level packages from the python install.
    python_root = distutils.sysconfig.get_python_lib(standard_lib=True)
    _, top_level_libs, _ = list(os.walk(python_root))[0]

    return sorted(top_level_libs + list(modules | system_modules))


def get_requirements():
    with pathlib.Path("requirements.txt").open() as requirements_txt:
        return {
            requirement.split("==")[0]
            for requirement in requirements_txt.read().split("\n")
            if not requirement.startswith("#") and "==" in requirement
        }


EXCLUDE_MODULES = {
    "homeassistant",
    *sys.builtin_module_names,
    *sys.modules,
    *NO_LOGGER_MODULES,
    *get_requirements(),
    *get_python_library(),
}


def get_pip_dep_tree():
    cache = {}

    for item in json.loads(
        subprocess.run(
            ["pipdeptree", "-w", "silence", "--json"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    ):
        cache[item["package"]["key"]] = {
            **item["package"],
            "dependencies": {dep["key"] for dep in item["dependencies"]},
        }
    return cache


def get_imports(path) -> Generator[Import]:
    with open(path) as fh:
        root = ast.parse(fh.read(), path)

    for node in ast.iter_child_nodes(root):
        if isinstance(node, ast.Import):
            module = []
            level = 0
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module.split(".")
            level = node.level
        else:
            continue

        for n in node.names:
            yield Import(module, n.name.split("."), n.asname, level)


def get_level_zero_imports(integration: str) -> set[str]:
    python_files = component_dir.glob(f"{integration}/**/*.py")
    modules = set()
    for py_file in python_files:
        for py_import in get_imports(py_file):
            if py_import.level != 0:
                continue
            if py_import.module:
                module = py_import.module[0]
            elif py_import.name:
                module = py_import.name[0]
            if module in EXCLUDE_MODULES:
                continue
            modules.add(module)
    return modules


if __name__ == "__main__":
    # Show the PyInstaller imports used in this file
    integrations = component_dir.glob("*/manifest.json")
    pip_dep_tree = get_pip_dep_tree()
    loggers_by_integration = {}
    for integration in integrations:
        name = integration.parent.name
        loggers = set()
        imports = get_level_zero_imports(name)
        for pkg in imports:
            loggers.add(pkg)
            if mod := pip_dep_tree.get(pkg):
                if deps := mod.get("dependencies"):
                    real_deps = {dep.replace("-", "_") for dep in deps}
                    loggers |= {dep for dep in real_deps if dep not in EXCLUDE_MODULES}
        loggers_by_integration[name] = {
            LOGGER_NAMES.get(logger, logger) for logger in loggers
        }

    pprint.pprint(loggers_by_integration)
