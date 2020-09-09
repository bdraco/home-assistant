"""DoorBird Media Source Implementation."""
import datetime as dt
import logging
import re
from typing import Optional, Tuple

from homeassistant.components.media_player.const import (
    MEDIA_CLASS_VIDEO,
    MEDIA_TYPE_VIDEO,
)
from homeassistant.components.media_player.errors import BrowseError
from homeassistant.components.media_source.const import MEDIA_MIME_TYPES
from homeassistant.components.media_source.error import MediaSourceError, Unresolvable
from homeassistant.components.media_source.models import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.core import HomeAssistant, callback

from .const import DATA_CAMERAS, DATA_EVENTS, DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)
MIME_TYPE = "application/x-mpegURL"


class IncompatibleMediaSource(MediaSourceError):
    """Incompatible media source attributes."""


async def async_get_media_source(hass: HomeAssistant):
    """Set up DoorBird media source."""
    return DoorBirdSource(hass)


class DoorBirdSource(MediaSource):
    """Provide DoorBird camera recordings as media sources."""

    name: str = MANUFACTURER

    def __init__(self, hass: HomeAssistant):
        """Initialize DoorBird source."""
        super().__init__(DOMAIN)
        self.hass = hass
        self.events = self.hass.data[DOMAIN][DATA_EVENTS]

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve media to a url."""
        _, camera_id, event_id = async_parse_identifier(item)
        url = self.events[camera_id][event_id]["media_url"]
        return PlayMedia(url, MIME_TYPE)

    async def async_browse_media(
        self, item: MediaSourceItem, media_types: Tuple[str] = MEDIA_MIME_TYPES
    ) -> BrowseMediaSource:
        """Return media."""
        try:
            source, camera_id, event_id = async_parse_identifier(item)
        except Unresolvable as err:
            raise BrowseError(str(err)) from err

        return self._browse_media(source, camera_id, event_id)

    def _browse_media(
        self, source: str, camera_id: str, event_id: int
    ) -> BrowseMediaSource:
        """Browse media."""
        if camera_id and camera_id not in self.events:
            raise BrowseError("Camera does not exist.")

        if event_id and event_id not in self.events[camera_id]:
            raise BrowseError("Event does not exist.")

        return self._build_item_response(source, camera_id, event_id)

    def _build_item_response(
        self, source: str, camera_id: str, event_id: int = None
    ) -> BrowseMediaSource:
        if event_id and event_id in self.events[camera_id]:
            created = dt.datetime.fromtimestamp(event_id)
            thumbnail = self.events[camera_id][event_id].get("snapshot", {}).get("url")
            message = remove_html_tags(self.events[camera_id][event_id]["message"])
            title = f"{created} - {message}"
        else:
            title = self.hass.data[DOMAIN][DATA_CAMERAS].get(camera_id, MANUFACTURER)
            thumbnail = None

        if event_id:
            path = f"{source}/{camera_id}/{event_id}"
        else:
            path = f"{source}/{camera_id}"

        media = BrowseMediaSource(
            domain=DOMAIN,
            identifier=path,
            media_class=MEDIA_CLASS_VIDEO,
            media_content_type=MEDIA_TYPE_VIDEO,
            title=title,
            can_play=bool(
                event_id and self.events[camera_id][event_id].get("media_url")
            ),
            can_expand=event_id is None,
            thumbnail=thumbnail,
        )

        if not media.can_play and not media.can_expand:
            _LOGGER.debug(
                "Camera %s with event %s without media url found", camera_id, event_id
            )
            raise IncompatibleMediaSource

        if not media.can_expand:
            return media

        media.children = []
        # Append first level children
        if not camera_id:
            for cid in self.events:
                child = self._build_item_response(source, cid)
                if child:
                    media.children.append(child)
        else:
            for eid in self.events[camera_id]:
                try:
                    child = self._build_item_response(source, camera_id, eid)
                except IncompatibleMediaSource:
                    continue
                if child:
                    media.children.append(child)

        return media


def remove_html_tags(text):
    """Remove html tags from string."""
    clean = re.compile("<.*?>")
    return re.sub(clean, "", text)


@callback
def async_parse_identifier(
    item: MediaSourceItem,
) -> Tuple[str, str, Optional[int]]:
    """Parse identifier."""
    if not item.identifier:
        return "events", "", None

    source, path = item.identifier.lstrip("/").split("/", 1)

    if source != "events":
        raise Unresolvable("Unknown source directory.")

    if "/" in path:
        camera_id, event_id = path.split("/", 1)
        return source, camera_id, int(event_id)

    return source, path, None
