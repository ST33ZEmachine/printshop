"""
ADK Trello Orders Agent package.

ADK expects this package to expose an `agent` module that defines `root_agent`.
"""

from . import agent  # noqa: F401
from .agent import root_agent  # noqa: F401

__all__ = ["root_agent"]


