"""Hardware-specific capture and output adapters."""

from framework.contrib.hardware.avermedia import AVerMediaCapture
from framework.contrib.hardware.replay import ReplayCapture
from framework.contrib.hardware.udp_xbox import UDPXboxOutput

__all__ = [
    "AVerMediaCapture",
    "ReplayCapture",
    "UDPXboxOutput",
]