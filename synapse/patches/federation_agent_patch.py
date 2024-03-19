
from __future__ import annotations
from typing import (
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from  urllib.parse import ParseResultBytes
    from twisted.web.http_headers import Headers


import logging
logger = logging.getLogger(__name__)


def patch_request_headers(request_headers: Headers, parsed_uri: ParseResultBytes) -> None:
    """
    Patches the request headers.
    Modifies the request headers in place.
    Host header.
    Currently, Synapse is not appending the default port to the host header, in some cases.

    Args:
        request_headers (Headers): The request headers to be patched.
        parsed_uri (ParseResultBytes): The parsed URI.

    Raises:
        Exception: If the host header cannot be set.
    """
    #& back_up_headers = request_headers.copy()
    try:
    
        return add_host_header_port(request_headers, parsed_uri)
    
    except Exception as e:
        logger.exception(f"Patch Failed to set host header for {parsed_uri} with error: {e}")
        #& request_headers = back_up_headers

def add_host_header_port(request_headers: Headers, parsed_uri: ParseResultBytes) -> None:
    """
    Adds a host header with default port to the request headers.

    Currently, Synapse is not appending the default port to the host header, in some cases.
    As federation servers per default use port 8448, to follow RFC spec, the default port should be
    appended to the host header if no port is specified other then 80 or 443.

    request_headers (dict like Headers) get modified in place.

    Args:
        request_headers (Headers): The request headers to which the host header will be added.
        parsed_uri (ParseResultBytes): The parsed URI.
    """
    default_port_host = set_default_port_host(parsed_uri)
    request_headers.setRawHeaders(b"host", [default_port_host])

def set_default_port_host(parsed_uri: ParseResultBytes, default_port: int = 8448) -> bytes:
    """
    Sets the default matrix port for the given URI if no port is specified in the URI.

    This function checks if a port is already specified in the URI. If a port is present,
    it returns the network location (netloc) as is. If no port is specified and the URI scheme
    is 'matrix-federation', it appends the default port to the netloc and returns it.

    This is done to not override a potential delegated port with a default port.

    Args:
        parsed_uri (ParseResultBytes): The URI to set the default port for.
        default_port (int, optional): The default port to set. Defaults to 8448.

    Returns:
        bytes: The network location with the default port set.

    Raises:
        ValueError: If no port is specified and no default port for the scheme.
    """
    
    if parsed_uri.port is not None and str(parsed_uri.port).encode() in parsed_uri.netloc:
        return parsed_uri.netloc

    if parsed_uri.port is None and parsed_uri.scheme == b'matrix-federation':
        return f"{parsed_uri.netloc.decode()}:{default_port}".encode()
    
    raise ValueError("No port specified and no default port for scheme")
