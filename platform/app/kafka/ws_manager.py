"""WebSocket connection manager with channel-based pub/sub."""
import asyncio
import json
import re
import time
from fastapi import WebSocket
from typing import Any


class WSManager:
    """Manages WebSocket connections with channel-based subscriptions."""

    def __init__(self):
        # {channel_name: set(websocket, ...)}
        self._channels: dict[str, set[WebSocket]] = {}
        # {websocket: set(channel_name, ...)}
        self._subscriptions: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        """Accept and register a new WebSocket connection."""
        await ws.accept()
        async with self._lock:
            self._subscriptions[ws] = set()

    async def disconnect(self, ws: WebSocket):
        """Remove a WebSocket and all its subscriptions."""
        async with self._lock:
            channels = self._subscriptions.pop(ws, set())
            for ch in channels:
                subs = self._channels.get(ch, set())
                subs.discard(ws)
                if not subs:
                    self._channels.pop(ch, None)

    async def subscribe(self, ws: WebSocket, channel: str):
        """Subscribe a connection to a channel."""
        if not self._is_canonical_channel(channel):
            raise ValueError(f"unsupported WebSocket channel: {channel}")
        async with self._lock:
            if channel not in self._channels:
                self._channels[channel] = set()
            self._channels[channel].add(ws)
            self._subscriptions.setdefault(ws, set()).add(channel)

    async def unsubscribe(self, ws: WebSocket, channel: str):
        """Unsubscribe a connection from a channel."""
        async with self._lock:
            subs = self._subscriptions.get(ws, set())
            subs.discard(channel)
            channel_subs = self._channels.get(channel, set())
            channel_subs.discard(ws)
            if not channel_subs:
                self._channels.pop(channel, None)

    async def broadcast(self, channel: str, message: dict[str, Any]):
        """Broadcast a message to all subscribers of a channel."""
        if not self._is_canonical_channel(channel):
            raise ValueError(f"unsupported WebSocket channel: {channel}")
        message_type = str(message.get("type", ""))
        if not self._is_canonical_message_type(message_type):
            raise ValueError(f"unsupported WebSocket message type: {message_type}")
        async with self._lock:
            subscribers = set(self._channels.get(channel, set()))

        if not subscribers:
            return

        payload = json.dumps(message, default=str)
        dead: list[WebSocket] = []

        for ws in subscribers:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        # Clean up dead connections
        for ws in dead:
            await self.disconnect(ws)

    async def handle_message(self, ws: WebSocket, raw: str):
        """Process an incoming WebSocket message (subscribe/unsubscribe/publish/ping)."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_text(json.dumps({"error": "invalid_json"}))
            return

        action = msg.get("action", "")

        if action == "subscribe":
            channels = self._message_channels(msg)
            for channel in channels:
                await self.subscribe(ws, channel)
            for channel in channels:
                await ws.send_text(json.dumps({
                    "action": "subscribed",
                    "channel": channel,
                    "ts": time.time(),
                }))

        elif action == "unsubscribe":
            channels = self._message_channels(msg)
            for channel in channels:
                await self.unsubscribe(ws, channel)
            for channel in channels:
                await ws.send_text(json.dumps({
                    "action": "unsubscribed",
                    "channel": channel,
                    "ts": time.time(),
                }))

        elif action == "publish":
            # Broadcast a message to all subscribers of a channel.
            # Used for dev/testing: inject mock data to verify frontend displays.
            # The message must contain "channel", "type", and "data" fields.
            channel = msg.get("channel", "")
            message_type = str(msg.get("type", ""))
            if not self._is_canonical_channel(channel):
                await ws.send_text(json.dumps({"error": "unsupported_channel"}))
                return
            if not self._is_canonical_message_type(message_type):
                await ws.send_text(json.dumps({"error": "unsupported_message_type"}))
                return
            broadcast_msg = {
                "channel": channel,
                "type": message_type,
                "data": msg.get("data", {}),
                "ts": time.time(),
            }
            await self.broadcast(channel, broadcast_msg)
            await ws.send_text(json.dumps({
                "action": "published",
                "channel": channel,
                "ts": time.time(),
            }))

        elif action == "ping":
            await ws.send_text(json.dumps({
                "action": "pong",
                "ts": time.time(),
            }))

    @property
    def channel_stats(self) -> dict[str, int]:
        """Return subscriber counts per channel."""
        return {ch: len(subs) for ch, subs in self._channels.items() if subs}

    @property
    def total_connections(self) -> int:
        return len(self._subscriptions)

    async def close_all(self):
        """Close all WebSocket connections."""
        async with self._lock:
            all_ws = list(self._subscriptions.keys())
        for ws in all_ws:
            try:
                await ws.close()
            except Exception:
                pass
        async with self._lock:
            self._channels.clear()
            self._subscriptions.clear()

    @staticmethod
    def _message_channels(msg: dict[str, Any]) -> list[str]:
        """Return subscription channel names from either channel or channels."""
        channels = msg.get("channels")
        if isinstance(channels, list):
            return [str(ch) for ch in channels if ch]
        channel = msg.get("channel", "")
        return [str(channel)] if channel else []

    @staticmethod
    def _is_canonical_channel(channel: str) -> bool:
        return bool(re.fullmatch(
            r"(?:uav_intersection:[^:]+|uav_alerts(?::[^:]+)?|uav_system|uav_telemetry:[^:]+|uav_calibration)",
            channel,
        ))

    @staticmethod
    def _is_canonical_message_type(message_type: str) -> bool:
        return bool(re.fullmatch(r"uav_[a-z0-9_]+", message_type))
