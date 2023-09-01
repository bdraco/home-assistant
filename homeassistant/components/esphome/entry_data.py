"""Runtime entry data for ESPHome stored in hass.data."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any, Final, TypedDict, cast

from aioesphomeapi import (
    COMPONENT_TYPE_TO_INFO,
    AlarmControlPanelInfo,
    APIClient,
    APIVersion,
    BinarySensorInfo,
    CameraInfo,
    CameraState,
    ClimateInfo,
    CoverInfo,
    DeviceInfo,
    EntityInfo,
    EntityState,
    FanInfo,
    LightInfo,
    LockInfo,
    MediaPlayerInfo,
    NumberInfo,
    SelectInfo,
    SensorInfo,
    SensorState,
    SwitchInfo,
    TextSensorInfo,
    UserService,
)
from aioesphomeapi.model import ButtonInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .bluetooth.device import ESPHomeBluetoothDevice
from .const import DOMAIN
from .dashboard import async_get_dashboard

INFO_TO_COMPONENT_TYPE: Final = {v: k for k, v in COMPONENT_TYPE_TO_INFO.items()}

_SENTINEL = object()
SAVE_DELAY = 120
_LOGGER = logging.getLogger(__name__)

# Mapping from ESPHome info type to HA platform
INFO_TYPE_TO_PLATFORM: dict[type[EntityInfo], Platform] = {
    AlarmControlPanelInfo: Platform.ALARM_CONTROL_PANEL,
    BinarySensorInfo: Platform.BINARY_SENSOR,
    ButtonInfo: Platform.BUTTON,
    CameraInfo: Platform.CAMERA,
    ClimateInfo: Platform.CLIMATE,
    CoverInfo: Platform.COVER,
    FanInfo: Platform.FAN,
    LightInfo: Platform.LIGHT,
    LockInfo: Platform.LOCK,
    MediaPlayerInfo: Platform.MEDIA_PLAYER,
    NumberInfo: Platform.NUMBER,
    SelectInfo: Platform.SELECT,
    SensorInfo: Platform.SENSOR,
    SwitchInfo: Platform.SWITCH,
    TextSensorInfo: Platform.SENSOR,
}


class StoreData(TypedDict, total=False):
    """ESPHome storage data."""

    device_info: dict[str, Any]
    services: list[dict[str, Any]]
    api_version: dict[str, Any]


class ESPHomeStorage(Store[StoreData]):
    """ESPHome Storage."""


@dataclass(slots=True)
class RuntimeEntryData:
    """Store runtime data for esphome config entries."""

    entry_id: str
    title: str
    client: APIClient
    store: ESPHomeStorage
    state: dict[type[EntityState], dict[int, EntityState]] = field(default_factory=dict)
    # When the disconnect callback is called, we mark all states
    # as stale so we will always dispatch a state update when the
    # device reconnects. This is the same format as state_subscriptions.
    stale_state: set[tuple[type[EntityState], int]] = field(default_factory=set)
    info: dict[type[EntityInfo], dict[int, EntityInfo]] = field(default_factory=dict)
    services: dict[int, UserService] = field(default_factory=dict)
    available: bool = False
    expected_disconnect: bool = False  # Last disconnect was expected (e.g. deep sleep)
    device_info: DeviceInfo | None = None
    bluetooth_device: ESPHomeBluetoothDevice | None = None
    api_version: APIVersion = field(default_factory=APIVersion)
    cleanup_callbacks: list[Callable[[], None]] = field(default_factory=list)
    disconnect_callbacks: list[Callable[[], None]] = field(default_factory=list)
    state_subscriptions: dict[
        tuple[type[EntityState], int], Callable[[], None]
    ] = field(default_factory=dict)
    loaded_platforms: set[Platform] = field(default_factory=set)
    platform_load_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _storage_contents: StoreData | None = None
    _pending_storage: Callable[[], StoreData] | None = None
    assist_pipeline_update_callbacks: list[Callable[[], None]] = field(
        default_factory=list
    )
    assist_pipeline_state: bool = False
    entity_info_callbacks: dict[
        type[EntityInfo], list[Callable[[list[EntityInfo]], None]]
    ] = field(default_factory=dict)
    entity_info_key_remove_callbacks: dict[
        tuple[type[EntityInfo], int], list[Callable[[], Coroutine[Any, Any, None]]]
    ] = field(default_factory=dict)
    entity_info_key_updated_callbacks: dict[
        tuple[type[EntityInfo], int], list[Callable[[EntityInfo], None]]
    ] = field(default_factory=dict)
    original_options: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Return the name of the device."""
        device_info = self.device_info
        return (device_info and device_info.name) or self.title

    @property
    def friendly_name(self) -> str:
        """Return the friendly name of the device."""
        device_info = self.device_info
        return (device_info and device_info.friendly_name) or self.name.title().replace(
            "_", " "
        )

    @property
    def signal_device_updated(self) -> str:
        """Return the signal to listen to for core device state update."""
        return f"esphome_{self.entry_id}_on_device_update"

    @property
    def signal_static_info_updated(self) -> str:
        """Return the signal to listen to for updates on static info."""
        return f"esphome_{self.entry_id}_on_list"

    @callback
    def async_register_static_info_callback(
        self,
        entity_info_type: type[EntityInfo],
        callback_: Callable[[list[EntityInfo]], None],
    ) -> CALLBACK_TYPE:
        """Register to receive callbacks when static info changes for an EntityInfo type."""
        callbacks = self.entity_info_callbacks.setdefault(entity_info_type, [])
        callbacks.append(callback_)

        def _unsub() -> None:
            callbacks.remove(callback_)

        return _unsub

    @callback
    def async_register_key_static_info_remove_callback(
        self,
        static_info: EntityInfo,
        callback_: Callable[[], Coroutine[Any, Any, None]],
    ) -> CALLBACK_TYPE:
        """Register to receive callbacks when static info is removed for a specific key."""
        callback_key = (type(static_info), static_info.key)
        callbacks = self.entity_info_key_remove_callbacks.setdefault(callback_key, [])
        callbacks.append(callback_)

        def _unsub() -> None:
            callbacks.remove(callback_)

        return _unsub

    @callback
    def async_register_key_static_info_updated_callback(
        self,
        static_info: EntityInfo,
        callback_: Callable[[EntityInfo], None],
    ) -> CALLBACK_TYPE:
        """Register to receive callbacks when static info is updated for a specific key."""
        callback_key = (type(static_info), static_info.key)
        callbacks = self.entity_info_key_updated_callbacks.setdefault(callback_key, [])
        callbacks.append(callback_)

        def _unsub() -> None:
            callbacks.remove(callback_)

        return _unsub

    @callback
    def async_set_assist_pipeline_state(self, state: bool) -> None:
        """Set the assist pipeline state."""
        self.assist_pipeline_state = state
        for update_callback in self.assist_pipeline_update_callbacks:
            update_callback()

    def async_subscribe_assist_pipeline_update(
        self, update_callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Subscribe to assist pipeline updates."""

        def _unsubscribe() -> None:
            self.assist_pipeline_update_callbacks.remove(update_callback)

        self.assist_pipeline_update_callbacks.append(update_callback)
        return _unsubscribe

    async def async_remove_entities(self, static_infos: Iterable[EntityInfo]) -> None:
        """Schedule the removal of an entity."""
        callbacks: list[Coroutine[Any, Any, None]] = []
        for static_info in static_infos:
            callback_key = (type(static_info), static_info.key)
            if key_callbacks := self.entity_info_key_remove_callbacks.get(callback_key):
                callbacks.extend([callback_() for callback_ in key_callbacks])
        if callbacks:
            await asyncio.gather(*callbacks)

    @callback
    def async_update_entity_infos(self, static_infos: Iterable[EntityInfo]) -> None:
        """Call static info updated callbacks."""
        for static_info in static_infos:
            callback_key = (type(static_info), static_info.key)
            for callback_ in self.entity_info_key_updated_callbacks.get(
                callback_key, []
            ):
                callback_(static_info)

    async def _ensure_platforms_loaded(
        self, hass: HomeAssistant, entry: ConfigEntry, platforms: set[Platform]
    ) -> None:
        async with self.platform_load_lock:
            needed = platforms - self.loaded_platforms
            if needed:
                await hass.config_entries.async_forward_entry_setups(entry, needed)
            self.loaded_platforms |= needed

    def _migrate_unique_ids_if_needed(
        self,
        ent_reg: er.EntityRegistry,
        possible_unique_id_migrations: dict[str, EntityInfo],
    ) -> None:
        """Migrate unique ids if needed."""
        assert self.device_info is not None
        old_unique_id_prefix = self.device_info.name
        possible_special_cases = set()
        for unique_id, info in possible_unique_id_migrations.items():
            platform = INFO_TYPE_TO_PLATFORM[type(info)]
            _, esphome_platform, object_id = unique_id.split("-", 2)
            old_unique_id = f"{old_unique_id_prefix}{esphome_platform}{object_id}"
            if old_entry := ent_reg.async_get_entity_id(
                platform, DOMAIN, old_unique_id
            ):
                ent_reg.async_update_entity(old_entry, new_unique_id=unique_id)
                continue
            # If we get here the old unique id may not be in the default format
            # and is likely a special case.
            #
            # Older ESPHome versions have the following special cases:
            #
            # <mac>-adc for esp8266 adc sensor only
            # <mac>-hall for esp32 hall sensor only
            # <mac>-uptime
            # <mac>-version
            # dallas-<dallas-address>
            #
            possible_special_cases.add(unique_id)

        if not possible_special_cases:
            return

        new_unique_id_prefix = f"{dr.format_mac(self.device_info.mac_address).upper()}-"
        current_entries_not_in_new_format: dict[str, er.RegistryEntry] = {}
        entry_id = self.entry_id
        for entry_id, entry in ent_reg.entities.items():
            unique_id = entry.unique_id
            if (
                entry.config_entry_id == entry_id
                and unique_id.count("-") != 2
                and not unique_id.startswith(new_unique_id_prefix)
            ):
                current_entries_not_in_new_format[entry_id] = entry

        # TODO: handle special cases here

    async def async_update_static_infos(
        self, hass: HomeAssistant, entry: ConfigEntry, infos: list[EntityInfo]
    ) -> None:
        """Distribute an update of static infos to all platforms."""
        ent_reg = er.async_get(hass)

        # First, load all platforms
        needed_platforms = set()
        new_unique_id_prefix: str | None = None

        if async_get_dashboard(hass):
            needed_platforms.add(Platform.UPDATE)

        if self.device_info is not None:
            new_unique_id_prefix = (
                f"{dr.format_mac(self.device_info.mac_address).upper()}-"
            )

            if self.device_info.voice_assistant_version:
                needed_platforms.add(Platform.BINARY_SENSOR)
                needed_platforms.add(Platform.SELECT)

        possible_unique_id_migrations: dict[str, EntityInfo] = {}

        for info in infos:
            platform = INFO_TYPE_TO_PLATFORM[type(info)]
            needed_platforms.add(platform)
            unique_id = info.unique_id
            # If the unique id is in the new format and does not already exist in the entity registry
            # then we need to migrate it from the old format if there is an entity with the old format
            if (
                new_unique_id_prefix
                and unique_id.startswith(new_unique_id_prefix)
                and unique_id.count("-") == 2
                and not ent_reg.async_get_entity_id(platform, DOMAIN, info.unique_id)
            ):
                possible_unique_id_migrations[unique_id] = info

        if possible_unique_id_migrations:
            _LOGGER.warning(
                "Possible unique id migrations: %s", possible_unique_id_migrations
            )
            self._migrate_unique_ids_if_needed(ent_reg, possible_unique_id_migrations)

        await self._ensure_platforms_loaded(hass, entry, needed_platforms)

        # Make a dict of the EntityInfo by type and send
        # them to the listeners for each specific EntityInfo type
        infos_by_type: dict[type[EntityInfo], list[EntityInfo]] = {}
        for info in infos:
            info_type = type(info)
            if info_type not in infos_by_type:
                infos_by_type[info_type] = []
            infos_by_type[info_type].append(info)

        callbacks_by_type = self.entity_info_callbacks
        for type_, entity_infos in infos_by_type.items():
            if callbacks_ := callbacks_by_type.get(type_):
                for callback_ in callbacks_:
                    callback_(entity_infos)

        # Then send dispatcher event
        async_dispatcher_send(hass, self.signal_static_info_updated, infos)

    @callback
    def async_subscribe_state_update(
        self,
        state_type: type[EntityState],
        state_key: int,
        entity_callback: Callable[[], None],
    ) -> Callable[[], None]:
        """Subscribe to state updates."""

        def _unsubscribe() -> None:
            self.state_subscriptions.pop((state_type, state_key))

        self.state_subscriptions[(state_type, state_key)] = entity_callback
        return _unsubscribe

    @callback
    def async_update_state(self, state: EntityState) -> None:
        """Distribute an update of state information to the target."""
        key = state.key
        state_type = type(state)
        stale_state = self.stale_state
        current_state_by_type = self.state[state_type]
        current_state = current_state_by_type.get(key, _SENTINEL)
        subscription_key = (state_type, key)
        debug_enabled = _LOGGER.isEnabledFor(logging.DEBUG)
        if (
            current_state == state
            and subscription_key not in stale_state
            and state_type is not CameraState
            and not (
                state_type is SensorState  # noqa: E721
                and (platform_info := self.info.get(SensorInfo))
                and (entity_info := platform_info.get(state.key))
                and (cast(SensorInfo, entity_info)).force_update
            )
        ):
            if debug_enabled:
                _LOGGER.debug(
                    "%s: ignoring duplicate update with key %s: %s",
                    self.name,
                    key,
                    state,
                )
            return
        if debug_enabled:
            _LOGGER.debug(
                "%s: dispatching update with key %s: %s",
                self.name,
                key,
                state,
            )
        stale_state.discard(subscription_key)
        current_state_by_type[key] = state
        if subscription := self.state_subscriptions.get(subscription_key):
            try:
                subscription()
            except Exception as ex:  # pylint: disable=broad-except
                # If we allow this exception to raise it will
                # make it all the way to data_received in aioesphomeapi
                # which will cause the connection to be closed.
                _LOGGER.exception("Error while calling subscription: %s", ex)

    @callback
    def async_update_device_state(self, hass: HomeAssistant) -> None:
        """Distribute an update of a core device state like availability."""
        async_dispatcher_send(hass, self.signal_device_updated)

    async def async_load_from_store(self) -> tuple[list[EntityInfo], list[UserService]]:
        """Load the retained data from store and return de-serialized data."""
        if (restored := await self.store.async_load()) is None:
            return [], []
        self._storage_contents = restored.copy()

        self.device_info = DeviceInfo.from_dict(restored.pop("device_info"))
        self.api_version = APIVersion.from_dict(restored.pop("api_version", {}))
        infos: list[EntityInfo] = []
        for comp_type, restored_infos in restored.items():
            if TYPE_CHECKING:
                restored_infos = cast(list[dict[str, Any]], restored_infos)
            if comp_type not in COMPONENT_TYPE_TO_INFO:
                continue
            for info in restored_infos:
                cls = COMPONENT_TYPE_TO_INFO[comp_type]
                infos.append(cls.from_dict(info))
        services = [
            UserService.from_dict(service) for service in restored.pop("services", [])
        ]
        return infos, services

    async def async_save_to_store(self) -> None:
        """Generate dynamic data to store and save it to the filesystem."""
        if TYPE_CHECKING:
            assert self.device_info is not None
        store_data: StoreData = {
            "device_info": self.device_info.to_dict(),
            "services": [],
            "api_version": self.api_version.to_dict(),
        }
        for info_type, infos in self.info.items():
            comp_type = INFO_TO_COMPONENT_TYPE[info_type]
            store_data[comp_type] = [info.to_dict() for info in infos.values()]  # type: ignore[literal-required]

        store_data["services"] = [
            service.to_dict() for service in self.services.values()
        ]
        if store_data == self._storage_contents:
            return

        def _memorized_storage() -> StoreData:
            self._pending_storage = None
            self._storage_contents = store_data
            return store_data

        self._pending_storage = _memorized_storage
        self.store.async_delay_save(_memorized_storage, SAVE_DELAY)

    async def async_cleanup(self) -> None:
        """Cleanup the entry data when disconnected or unloading."""
        if self._pending_storage:
            # Ensure we save the data if we are unloading before the
            # save delay has passed.
            await self.store.async_save(self._pending_storage())

    async def async_update_listener(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Handle options update."""
        if self.original_options == entry.options:
            return
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
