"""Slash command routing and built-in handlers."""

from secbot.command.builtin import register_builtin_commands
from secbot.command.router import CommandContext, CommandRouter

__all__ = ["CommandContext", "CommandRouter", "register_builtin_commands"]
