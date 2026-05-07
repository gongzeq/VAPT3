"""Chat channels module with plugin architecture."""

from secbot.channels.base import BaseChannel
from secbot.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
