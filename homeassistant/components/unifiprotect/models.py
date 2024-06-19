"""The unifiprotect integration models."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from functools import partial
import logging
from operator import attrgetter
from typing import Any, Generic, TypeVar

from uiprotect.data import NVR, Event, ProtectAdoptableDeviceModel

from homeassistant.helpers.entity import EntityDescription

from .utils import (
    get_nested_attr,
    get_nested_attr_as_bool,
    get_top_level_attr,
    get_top_level_attr_as_bool,
)

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T", bound=ProtectAdoptableDeviceModel | NVR)


class PermRequired(int, Enum):
    """Type of permission level required for entity."""

    NO_WRITE = 1
    WRITE = 2
    DELETE = 3


@dataclass(frozen=True, kw_only=True)
class ProtectEntityDescription(EntityDescription, Generic[T]):
    """Base class for protect entity descriptions."""

    ufp_required_field: str | None = None
    ufp_value: str | None = None
    ufp_value_fn: Callable[[T], Any] | None = None
    ufp_enabled: str | None = None
    ufp_perm: PermRequired | None = None

    # The below are set in __post_init__
    has_required: Callable[[T], bool] = bool
    get_ufp_enabled: Callable[[T], bool] = bool

    def get_ufp_value(self, obj: T) -> Any:
        """Return value from UniFi Protect device; overridden in __post_init__."""
        # ufp_value or ufp_value_fn are required, the
        # RuntimeError is to catch any issues in the code
        # with new descriptions.
        raise RuntimeError(  # pragma: no cover
            f"`ufp_value` or `ufp_value_fn` is required for {self}"
        )

    def __post_init__(self) -> None:
        """Override get_ufp_value, has_required, and get_ufp_enabled if required."""
        _setter = partial(object.__setattr__, self)

        if (ufp_value := self.ufp_value) is not None:
            _setter("get_ufp_value", make_value_getter(ufp_value))
        elif (ufp_value_fn := self.ufp_value_fn) is not None:
            _setter("get_ufp_value", ufp_value_fn)

        if (ufp_enabled := self.ufp_enabled) is not None:
            _setter("get_ufp_enabled", make_enable_getter(ufp_enabled))

        if (ufp_required_field := self.ufp_required_field) is not None:
            _setter("has_required", make_required_getter(ufp_required_field))


def make_value_getter(ufp_value: str) -> Callable[[T], Any]:
    """Return a function to get a value from a Protect device."""
    if "." not in ufp_value:
        return partial(get_top_level_attr, ufp_value)
    return partial(get_nested_attr, tuple(ufp_value.split(".")))


def make_enable_getter(ufp_enabled: str) -> Callable[[T], bool]:
    """Return a function to get a value from a Protect device."""
    if "." not in ufp_enabled:
        return attrgetter(ufp_enabled)
    return partial(get_nested_attr, tuple(ufp_enabled.split(".")))


def make_required_getter(ufp_required_field: str) -> Callable[[T], bool]:
    """Return a function to get a value from a Protect device."""
    if "." not in ufp_required_field:
        return partial(get_top_level_attr_as_bool, ufp_required_field)
    return partial(get_nested_attr_as_bool, tuple(ufp_required_field.split(".")))


@dataclass(frozen=True, kw_only=True)
class ProtectEventMixin(ProtectEntityDescription[T]):
    """Mixin for events."""

    ufp_event_obj: str | None = None

    def get_event_obj(self, obj: T) -> Event | None:
        """Return value from UniFi Protect device."""
        return None

    def __post_init__(self) -> None:
        """Override get_event_obj if ufp_event_obj is set."""
        if (_ufp_event_obj := self.ufp_event_obj) is not None:
            object.__setattr__(self, "get_event_obj", attrgetter(_ufp_event_obj))
        super().__post_init__()

    def get_is_on(self, obj: T, event: Event | None) -> bool:
        """Return value if event is active."""
        return event is not None and self.get_ufp_value(obj)


@dataclass(frozen=True, kw_only=True)
class ProtectSetableKeysMixin(ProtectEntityDescription[T]):
    """Mixin for settable values."""

    ufp_set_method: str | None = None
    ufp_set_method_fn: Callable[[T, Any], Coroutine[Any, Any, None]] | None = None

    async def ufp_set(self, obj: T, value: Any) -> None:
        """Set value for UniFi Protect device."""
        _LOGGER.debug("Setting %s to %s for %s", self.name, value, obj.display_name)
        if self.ufp_set_method is not None:
            await getattr(obj, self.ufp_set_method)(value)
        elif self.ufp_set_method_fn is not None:
            await self.ufp_set_method_fn(obj, value)
