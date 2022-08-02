"""Tests for pylint hass_enforce_type_hints plugin."""
# pylint:disable=protected-access
from __future__ import annotations

import re
from types import ModuleType
from unittest.mock import patch

import astroid
from pylint.checkers import BaseChecker
import pylint.testutils
from pylint.testutils.unittest_linter import UnittestLinter
import pytest

from . import assert_adds_messages, assert_no_messages


@pytest.mark.parametrize(
    ("module_name", "expected_platform", "in_platforms"),
    [
        ("homeassistant", None, False),
        ("homeassistant.components", None, False),
        ("homeassistant.components.pylint_test", "__init__", False),
        ("homeassistant.components.pylint_test.config_flow", "config_flow", False),
        ("homeassistant.components.pylint_test.light", "light", True),
        ("homeassistant.components.pylint_test.light.v1", None, False),
    ],
)
def test_regex_get_module_platform(
    hass_enforce_type_hints: ModuleType,
    module_name: str,
    expected_platform: str | None,
    in_platforms: bool,
) -> None:
    """Test _get_module_platform regex."""
    platform = hass_enforce_type_hints._get_module_platform(module_name)

    assert platform == expected_platform
    assert (platform in hass_enforce_type_hints._PLATFORMS) == in_platforms


@pytest.mark.parametrize(
    ("string", "expected_count", "expected_items"),
    [
        ("Callable[..., None]", 2, ("Callable", "...", "None")),
        ("Callable[..., Awaitable[None]]", 2, ("Callable", "...", "Awaitable[None]")),
        ("tuple[int, int, int, int]", 4, ("tuple", "int", "int", "int", "int")),
        (
            "tuple[int, int, int, int, int]",
            5,
            ("tuple", "int", "int", "int", "int", "int"),
        ),
        ("Awaitable[None]", 1, ("Awaitable", "None")),
        ("list[dict[str, str]]", 1, ("list", "dict[str, str]")),
        ("list[dict[str, Any]]", 1, ("list", "dict[str, Any]")),
    ],
)
def test_regex_x_of_y_i(
    hass_enforce_type_hints: ModuleType,
    string: str,
    expected_count: int,
    expected_items: tuple[str, ...],
) -> None:
    """Test x_of_y_i regexes."""
    matchers: dict[str, re.Pattern] = hass_enforce_type_hints._TYPE_HINT_MATCHERS

    assert (match := matchers[f"x_of_y_{expected_count}"].match(string))
    assert match.group(0) == string
    for index in range(expected_count):
        assert match.group(index + 1) == expected_items[index]


@pytest.mark.parametrize(
    ("string", "expected_a", "expected_b"),
    [("DiscoveryInfoType | None", "DiscoveryInfoType", "None")],
)
def test_regex_a_or_b(
    hass_enforce_type_hints: ModuleType, string: str, expected_a: str, expected_b: str
) -> None:
    """Test a_or_b regexes."""
    matchers: dict[str, re.Pattern] = hass_enforce_type_hints._TYPE_HINT_MATCHERS

    assert (match := matchers["a_or_b"].match(string))
    assert match.group(0) == string
    assert match.group(1) == expected_a
    assert match.group(2) == expected_b


@pytest.mark.parametrize(
    "code",
    [
        """
    async def setup( #@
        arg1, arg2
    ):
        pass
    """
    ],
)
def test_ignore_no_annotations(
    hass_enforce_type_hints: ModuleType, type_hint_checker: BaseChecker, code: str
) -> None:
    """Ensure that _is_valid_type is not run if there are no annotations."""
    # Set ignore option
    type_hint_checker.config.ignore_missing_annotations = True

    func_node = astroid.extract_node(
        code,
        "homeassistant.components.pylint_test",
    )
    type_hint_checker.visit_module(func_node.parent)

    with patch.object(
        hass_enforce_type_hints, "_is_valid_type", return_value=True
    ) as is_valid_type:
        type_hint_checker.visit_asyncfunctiondef(func_node)
        is_valid_type.assert_not_called()


@pytest.mark.parametrize(
    "code",
    [
        """
    async def setup( #@
        arg1, arg2
    ):
        pass
    """
    ],
)
def test_bypass_ignore_no_annotations(
    hass_enforce_type_hints: ModuleType, type_hint_checker: BaseChecker, code: str
) -> None:
    """Test `ignore-missing-annotations` option.

    Ensure that `_is_valid_type` is run if there are no annotations
    but `ignore-missing-annotations` option is forced to False.
    """
    # Set bypass option
    type_hint_checker.config.ignore_missing_annotations = False

    func_node = astroid.extract_node(
        code,
        "homeassistant.components.pylint_test",
    )
    type_hint_checker.visit_module(func_node.parent)

    with patch.object(
        hass_enforce_type_hints, "_is_valid_type", return_value=True
    ) as is_valid_type:
        type_hint_checker.visit_asyncfunctiondef(func_node)
        is_valid_type.assert_called()


@pytest.mark.parametrize(
    "code",
    [
        """
    async def setup( #@
        arg1: ArgHint, arg2
    ):
        pass
    """,
        """
    async def setup( #@
        arg1, arg2
    ) -> ReturnHint:
        pass
    """,
        """
    async def setup( #@
        arg1: ArgHint, arg2: ArgHint
    ) -> ReturnHint:
        pass
    """,
    ],
)
def test_dont_ignore_partial_annotations(
    hass_enforce_type_hints: ModuleType, type_hint_checker: BaseChecker, code: str
) -> None:
    """Ensure that _is_valid_type is run if there is at least one annotation."""
    func_node = astroid.extract_node(
        code,
        "homeassistant.components.pylint_test",
    )
    type_hint_checker.visit_module(func_node.parent)

    with patch.object(
        hass_enforce_type_hints, "_is_valid_type", return_value=True
    ) as is_valid_type:
        type_hint_checker.visit_asyncfunctiondef(func_node)
        is_valid_type.assert_called()


def test_invalid_discovery_info(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure invalid hints are rejected for discovery_info."""
    func_node, discovery_info_node = astroid.extract_node(
        """
    async def async_setup_scanner( #@
        hass: HomeAssistant,
        config: ConfigType,
        async_see: AsyncSeeCallback,
        discovery_info: dict[str, Any] | None = None, #@
    ) -> bool:
        pass
    """,
        "homeassistant.components.pylint_test.device_tracker",
    )
    type_hint_checker.visit_module(func_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-argument-type",
            node=discovery_info_node,
            args=(4, "DiscoveryInfoType | None", "async_setup_scanner"),
            line=6,
            col_offset=4,
            end_line=6,
            end_col_offset=41,
        ),
    ):
        type_hint_checker.visit_asyncfunctiondef(func_node)


def test_valid_discovery_info(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure valid hints are accepted for discovery_info."""
    func_node = astroid.extract_node(
        """
    async def async_setup_scanner( #@
        hass: HomeAssistant,
        config: ConfigType,
        async_see: AsyncSeeCallback,
        discovery_info: DiscoveryInfoType | None = None,
    ) -> bool:
        pass
    """,
        "homeassistant.components.pylint_test.device_tracker",
    )
    type_hint_checker.visit_module(func_node.parent)

    with assert_no_messages(linter):
        type_hint_checker.visit_asyncfunctiondef(func_node)


def test_invalid_list_dict_str_any(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure invalid hints are rejected for discovery_info."""
    func_node = astroid.extract_node(
        """
    async def async_get_triggers( #@
        hass: HomeAssistant,
        device_id: str
    ) -> list:
        pass
    """,
        "homeassistant.components.pylint_test.device_trigger",
    )
    type_hint_checker.visit_module(func_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=func_node,
            args=(
                ["list[dict[str, str]]", "list[dict[str, Any]]"],
                "async_get_triggers",
            ),
            line=2,
            col_offset=0,
            end_line=2,
            end_col_offset=28,
        ),
    ):
        type_hint_checker.visit_asyncfunctiondef(func_node)


def test_valid_list_dict_str_any(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure valid hints are accepted for discovery_info."""
    func_node = astroid.extract_node(
        """
    async def async_get_triggers( #@
        hass: HomeAssistant,
        device_id: str
    ) -> list[dict[str, Any]]:
        pass
    """,
        "homeassistant.components.pylint_test.device_trigger",
    )
    type_hint_checker.visit_module(func_node.parent)

    with assert_no_messages(linter):
        type_hint_checker.visit_asyncfunctiondef(func_node)


def test_invalid_config_flow_step(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure invalid hints are rejected for ConfigFlow step."""
    class_node, func_node, arg_node = astroid.extract_node(
        """
    class FlowHandler():
        pass

    class ConfigFlow(FlowHandler):
        pass

    class AxisFlowHandler( #@
        ConfigFlow, domain=AXIS_DOMAIN
    ):
        async def async_step_zeroconf( #@
            self,
            device_config: dict #@
        ):
            pass
    """,
        "homeassistant.components.pylint_test.config_flow",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-argument-type",
            node=arg_node,
            args=(2, "ZeroconfServiceInfo", "async_step_zeroconf"),
            line=13,
            col_offset=8,
            end_line=13,
            end_col_offset=27,
        ),
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=func_node,
            args=("FlowResult", "async_step_zeroconf"),
            line=11,
            col_offset=4,
            end_line=11,
            end_col_offset=33,
        ),
    ):
        type_hint_checker.visit_classdef(class_node)


def test_valid_config_flow_step(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure valid hints are accepted for ConfigFlow step."""
    class_node = astroid.extract_node(
        """
    class FlowHandler():
        pass

    class ConfigFlow(FlowHandler):
        pass

    class AxisFlowHandler( #@
        ConfigFlow, domain=AXIS_DOMAIN
    ):
        async def async_step_zeroconf(
            self,
            device_config: ZeroconfServiceInfo
        ) -> FlowResult:
            pass
    """,
        "homeassistant.components.pylint_test.config_flow",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_no_messages(linter):
        type_hint_checker.visit_classdef(class_node)


def test_invalid_config_flow_async_get_options_flow(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure invalid hints are rejected for ConfigFlow async_get_options_flow."""
    # AxisOptionsFlow doesn't inherit OptionsFlow, and therefore should fail
    class_node, func_node, arg_node = astroid.extract_node(
        """
    class FlowHandler():
        pass

    class ConfigFlow(FlowHandler):
        pass

    class OptionsFlow(FlowHandler):
        pass

    class AxisOptionsFlow():
        pass

    class AxisFlowHandler( #@
        ConfigFlow, domain=AXIS_DOMAIN
    ):
        def async_get_options_flow( #@
            config_entry #@
        ) -> AxisOptionsFlow:
            return AxisOptionsFlow(config_entry)
    """,
        "homeassistant.components.pylint_test.config_flow",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-argument-type",
            node=arg_node,
            args=(1, "ConfigEntry", "async_get_options_flow"),
            line=18,
            col_offset=8,
            end_line=18,
            end_col_offset=20,
        ),
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=func_node,
            args=("OptionsFlow", "async_get_options_flow"),
            line=17,
            col_offset=4,
            end_line=17,
            end_col_offset=30,
        ),
    ):
        type_hint_checker.visit_classdef(class_node)


def test_valid_config_flow_async_get_options_flow(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure valid hints are accepted for ConfigFlow async_get_options_flow."""
    class_node = astroid.extract_node(
        """
    class FlowHandler():
        pass

    class ConfigFlow(FlowHandler):
        pass

    class OptionsFlow(FlowHandler):
        pass

    class AxisOptionsFlow(OptionsFlow):
        pass

    class OtherOptionsFlow(OptionsFlow):
        pass

    class AxisFlowHandler( #@
        ConfigFlow, domain=AXIS_DOMAIN
    ):
        def async_get_options_flow(
            config_entry: ConfigEntry
        ) -> AxisOptionsFlow | OtherOptionsFlow | OptionsFlow:
            if self.use_other:
                return OtherOptionsFlow(config_entry)
            return AxisOptionsFlow(config_entry)

    """,
        "homeassistant.components.pylint_test.config_flow",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_no_messages(linter):
        type_hint_checker.visit_classdef(class_node)


def test_invalid_entity_properties(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Check missing entity properties when ignore_missing_annotations is False."""
    # Set bypass option
    type_hint_checker.config.ignore_missing_annotations = False

    class_node, prop_node, func_node = astroid.extract_node(
        """
    class Entity():
        pass

    class LockEntity(Entity):
        pass

    class DoorLock( #@
        LockEntity
    ):
        @property
        def changed_by( #@
            self
        ):
            pass

        async def async_lock( #@
            self,
            **kwargs
        ) -> bool:
            pass
    """,
        "homeassistant.components.pylint_test.lock",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=prop_node,
            args=(["str", None], "changed_by"),
            line=12,
            col_offset=4,
            end_line=12,
            end_col_offset=18,
        ),
        pylint.testutils.MessageTest(
            msg_id="hass-argument-type",
            node=func_node,
            args=("kwargs", "Any", "async_lock"),
            line=17,
            col_offset=4,
            end_line=17,
            end_col_offset=24,
        ),
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=func_node,
            args=("None", "async_lock"),
            line=17,
            col_offset=4,
            end_line=17,
            end_col_offset=24,
        ),
    ):
        type_hint_checker.visit_classdef(class_node)


def test_ignore_invalid_entity_properties(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Check invalid entity properties are ignored by default."""
    # Set ignore option
    type_hint_checker.config.ignore_missing_annotations = True

    class_node = astroid.extract_node(
        """
    class Entity():
        pass

    class LockEntity(Entity):
        pass

    class DoorLock( #@
        LockEntity
    ):
        @property
        def changed_by(
            self
        ):
            pass

        async def async_lock(
            self,
            **kwargs
        ) -> bool:
            pass
    """,
        "homeassistant.components.pylint_test.lock",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_no_messages(linter):
        type_hint_checker.visit_classdef(class_node)


def test_named_arguments(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Check missing entity properties when ignore_missing_annotations is False."""
    # Set bypass option
    type_hint_checker.config.ignore_missing_annotations = False

    class_node, func_node, percentage_node, preset_mode_node = astroid.extract_node(
        """
    class Entity():
        pass

    class ToggleEntity(Entity):
        pass

    class FanEntity(ToggleEntity):
        pass

    class MyFan( #@
        FanEntity
    ):
        async def async_turn_on( #@
            self,
            percentage, #@
            *,
            preset_mode: str, #@
            **kwargs
        ) -> bool:
            pass
    """,
        "homeassistant.components.pylint_test.fan",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-argument-type",
            node=percentage_node,
            args=("percentage", "int | None", "async_turn_on"),
            line=16,
            col_offset=8,
            end_line=16,
            end_col_offset=18,
        ),
        pylint.testutils.MessageTest(
            msg_id="hass-argument-type",
            node=preset_mode_node,
            args=("preset_mode", "str | None", "async_turn_on"),
            line=18,
            col_offset=8,
            end_line=18,
            end_col_offset=24,
        ),
        pylint.testutils.MessageTest(
            msg_id="hass-argument-type",
            node=func_node,
            args=("kwargs", "Any", "async_turn_on"),
            line=14,
            col_offset=4,
            end_line=14,
            end_col_offset=27,
        ),
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=func_node,
            args=("None", "async_turn_on"),
            line=14,
            col_offset=4,
            end_line=14,
            end_col_offset=27,
        ),
    ):
        type_hint_checker.visit_classdef(class_node)


@pytest.mark.parametrize(
    "return_hint",
    [
        "",
        "-> Mapping[int, int]",
        "-> dict[int, Any]",
    ],
)
def test_invalid_mapping_return_type(
    linter: UnittestLinter,
    type_hint_checker: BaseChecker,
    return_hint: str,
) -> None:
    """Check that Mapping[xxx, Any] doesn't accept invalid Mapping or dict."""
    # Set bypass option
    type_hint_checker.config.ignore_missing_annotations = False

    class_node, property_node = astroid.extract_node(
        f"""
    class Entity():
        pass

    class ToggleEntity(Entity):
        pass

    class FanEntity(ToggleEntity):
        pass

    class MyFanA( #@
        FanEntity
    ):
        @property
        def capability_attributes( #@
            self
        ){return_hint}:
            pass
    """,
        "homeassistant.components.pylint_test.fan",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=property_node,
            args=(["Mapping[str, Any]", None], "capability_attributes"),
            line=15,
            col_offset=4,
            end_line=15,
            end_col_offset=29,
        ),
    ):
        type_hint_checker.visit_classdef(class_node)


@pytest.mark.parametrize(
    "return_hint",
    [
        "-> Mapping[str, Any]",
        "-> Mapping[str, bool | int]",
        "-> dict[str, Any]",
        "-> dict[str, str]",
    ],
)
def test_valid_mapping_return_type(
    linter: UnittestLinter,
    type_hint_checker: BaseChecker,
    return_hint: str,
) -> None:
    """Check that Mapping[xxx, Any] accepts both Mapping and dict."""
    # Set bypass option
    type_hint_checker.config.ignore_missing_annotations = False

    class_node = astroid.extract_node(
        f"""
    class Entity():
        pass

    class ToggleEntity(Entity):
        pass

    class FanEntity(ToggleEntity):
        pass

    class MyFanA( #@
        FanEntity
    ):
        @property
        def capability_attributes(
            self
        ){return_hint}:
            pass
    """,
        "homeassistant.components.pylint_test.fan",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_no_messages(linter):
        type_hint_checker.visit_classdef(class_node)


def test_valid_long_tuple(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Check invalid entity properties are ignored by default."""
    # Set ignore option
    type_hint_checker.config.ignore_missing_annotations = False

    class_node, _, _ = astroid.extract_node(
        """
    class Entity():
        pass

    class ToggleEntity(Entity):
        pass

    class LightEntity(ToggleEntity):
        pass

    class TestLight( #@
        LightEntity
    ):
        @property
        def rgbw_color( #@
            self
        ) -> tuple[int, int, int, int]:
            pass

        @property
        def rgbww_color( #@
            self
        ) -> tuple[int, int, int, int, int]:
            pass
    """,
        "homeassistant.components.pylint_test.light",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_no_messages(linter):
        type_hint_checker.visit_classdef(class_node)


def test_invalid_long_tuple(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Check invalid entity properties are ignored by default."""
    # Set ignore option
    type_hint_checker.config.ignore_missing_annotations = False

    class_node, rgbw_node, rgbww_node = astroid.extract_node(
        """
    class Entity():
        pass

    class ToggleEntity(Entity):
        pass

    class LightEntity(ToggleEntity):
        pass

    class TestLight( #@
        LightEntity
    ):
        @property
        def rgbw_color( #@
            self
        ) -> tuple[int, int, int, int, int]:
            pass

        @property
        def rgbww_color( #@
            self
        ) -> tuple[int, int, int, int, float]:
            pass
    """,
        "homeassistant.components.pylint_test.light",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=rgbw_node,
            args=(["tuple[int, int, int, int]", None], "rgbw_color"),
            line=15,
            col_offset=4,
            end_line=15,
            end_col_offset=18,
        ),
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=rgbww_node,
            args=(["tuple[int, int, int, int, int]", None], "rgbww_color"),
            line=21,
            col_offset=4,
            end_line=21,
            end_col_offset=19,
        ),
    ):
        type_hint_checker.visit_classdef(class_node)


def test_invalid_device_class(
    linter: UnittestLinter, type_hint_checker: BaseChecker
) -> None:
    """Ensure invalid hints are rejected for entity device_class."""
    # Set bypass option
    type_hint_checker.config.ignore_missing_annotations = False

    class_node, prop_node = astroid.extract_node(
        """
    class Entity():
        pass

    class CoverEntity(Entity):
        pass

    class MyCover( #@
        CoverEntity
    ):
        @property
        def device_class( #@
            self
        ):
            pass
    """,
        "homeassistant.components.pylint_test.cover",
    )
    type_hint_checker.visit_module(class_node.parent)

    with assert_adds_messages(
        linter,
        pylint.testutils.MessageTest(
            msg_id="hass-return-type",
            node=prop_node,
            args=(["CoverDeviceClass", "str", None], "device_class"),
            line=12,
            col_offset=4,
            end_line=12,
            end_col_offset=20,
        ),
    ):
        type_hint_checker.visit_classdef(class_node)
