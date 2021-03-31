"""Code to handle a DenonAVR receiver."""
import logging
from typing import Callable, Optional

from denonavr import DenonAVR
from denonavr.exceptions import AvrNetworkError, AvrTimoutError

from homeassistant.config_entries import ENTRY_STATE_SETUP_RETRY

_LOGGER = logging.getLogger(__name__)


class ConnectDenonAVR:
    """Class to async connect to a DenonAVR receiver."""

    def __init__(
        self,
        host: str,
        timeout: float,
        show_all_inputs: bool,
        zone2: bool,
        zone3: bool,
        async_client_getter: Callable,
        entry_state: Optional[str] = None,
    ):
        """Initialize the class."""
        self._async_client_getter = async_client_getter
        self._receiver = None
        self._host = host
        self._show_all_inputs = show_all_inputs
        self._timeout = timeout
        self._entry_state = entry_state

        self._zones = {}
        if zone2:
            self._zones["Zone2"] = None
        if zone3:
            self._zones["Zone3"] = None

    @property
    def receiver(self) -> Optional[DenonAVR]:
        """Return the class containing all connections to the receiver."""
        return self._receiver

    async def async_connect_receiver(self) -> bool:
        """Connect to the DenonAVR receiver."""
        if not await self.async_init_receiver_class():
            return False

        if (
            self._receiver.manufacturer is None
            or self._receiver.name is None
            or self._receiver.model_name is None
            or self._receiver.receiver_type is None
        ):
            _LOGGER.error(
                "Missing receiver information: manufacturer '%s', name '%s', model '%s', type '%s'",
                self._receiver.manufacturer,
                self._receiver.name,
                self._receiver.model_name,
                self._receiver.receiver_type,
            )
            return False

        _LOGGER.debug(
            "%s receiver %s at host %s connected, model %s, serial %s, type %s",
            self._receiver.manufacturer,
            self._receiver.name,
            self._receiver.host,
            self._receiver.model_name,
            self._receiver.serial_number,
            self._receiver.receiver_type,
        )

        return True

    async def async_init_receiver_class(self) -> bool:
        """Initialize the DenonAVR class asynchronously."""
        receiver = DenonAVR(
            host=self._host,
            show_all_inputs=self._show_all_inputs,
            timeout=self._timeout,
            add_zones=self._zones,
        )
        # Use httpx.AsyncClient getter provided by Home Assistant
        receiver.set_async_client_getter(self._async_client_getter)
        try:
            await receiver.async_setup()
        except AvrTimoutError:
            if self._entry_state == ENTRY_STATE_SETUP_RETRY:
                _LOGGER.debug(
                    "Timeout error during setup of denonavr on host %s", self._host
                )
            else:
                _LOGGER.error(
                    "Timeout error during setup of denonavr on host %s", self._host
                )
            return False
        except AvrNetworkError:
            if self._entry_state == ENTRY_STATE_SETUP_RETRY:
                _LOGGER.debug(
                    "Network error during setup of denonavr on host %s", self._host
                )
            else:
                _LOGGER.error(
                    "Network error during setup of denonavr on host %s", self._host
                )
            return False

        self._receiver = receiver

        return True
