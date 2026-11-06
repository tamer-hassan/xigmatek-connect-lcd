"""Linux counterpart to the ALPHA app for Xigmatek Connect AIO coolers."""
from . import protocol, render, sensors
from .protocol import (Link, Message, ProtocolError, decode, encode,
                       find_ports)

__version__ = "0.1"

# the module is called render, so its draw entry point is aliased at the top
# level for convenience
render_frame = render.draw

__all__ = ["protocol", "render", "sensors", "Link", "Message", "ProtocolError",
           "decode", "encode", "find_ports", "render_frame", "__version__"]
