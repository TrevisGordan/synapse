import urllib.parse

from synapse.patches.federation_agent_patch import (
    set_default_port_host,
    add_host_header_port,
)

from twisted.web.http_headers import Headers

import pytest


def create_parsed_uri(
    host: str,
    scheme: str = "https",
    port: int = 0,
    path: str = "",
    params: str = "",
    query: str = "",
    fragment: str = "",
):
    """
    Creates a parsed URI using the provided components.

    Args:
        host (str): The hostname of the URI.
        scheme (str, optional): The scheme of the URI (e.g., 'http', 'https'). Defaults to 'http'.
        port (int, optional): The port number for the URI. Defaults to None.
        path (str, optional): The path of the URI. Defaults to ''.
        params (str, optional): The parameters for the URI. Defaults to ''.
        query (str, optional): The query component of the URI. Defaults to ''.
        fragment (str, optional): The fragment identifier of the URI. Defaults to ''.

    Returns:
        ParseResultBytes: The parsed URI.
    """
    netloc = f"{host}:{port}" if port else host
    uri = urllib.parse.urlunparse(
        (scheme, netloc, path, params, query, fragment)
    ).encode()
    return urllib.parse.urlparse(uri)


class TestSetDefaultPortHost:
    # Returns bytesting with the default port for the scheme.
    def test_returns_bytes(self):
        parsed_uri = create_parsed_uri("example.com", scheme="matrix-federation")
        result = set_default_port_host(parsed_uri)
        assert isinstance(result, bytes)

    @pytest.mark.parametrize(
        "host, scheme, port",
        [
            ("example.com", "matrix-federation", 8448),
            ("example.com", "matrix-federation", 1234),
            ("example.org", "matrix-federation", 5678),
            ("test.com", "http", 8080),
            ("localhost", "https", 443),
            ("localhost", "https", 443),
        ],
    )
    def test_returns_netloc_as_is_if_port_specified(self, host, scheme, port):
        parsed_uri = create_parsed_uri(host, scheme=scheme, port=port)
        result = set_default_port_host(parsed_uri)
        expected = f"{host}:{port}".encode()
        assert result == expected

    @pytest.mark.parametrize(
        "host, scheme, default_port",
        [
            ("example.com", "matrix-federation", 9000),
            ("example.org", "matrix-federation", 8000),
            ("test.com", "matrix-federation", 7000),
            ("localhost", "matrix-federation", 6000),
            ("mywebsite.com", "matrix-federation", 5000),
        ],
    )
    def test_appends_default_port_to_netloc(self, host, scheme, default_port):
        parsed_uri = create_parsed_uri(host, scheme=scheme)
        result = set_default_port_host(parsed_uri, default_port=default_port)
        expected = f"{host}:{default_port}".encode()
        assert result == expected

    # Raises a ValueError if the URI scheme is not 'matrix-federation' and no port is specified.
    # ! Should we even do this ? -> as it could be 80 or 443 default. ?
    def test_raises_value_error_if_scheme_not_matrix_federation_and_no_port_specified(
        self,
    ):
        parsed_uri = create_parsed_uri("example.com", scheme="http")
        with pytest.raises(ValueError):
            set_default_port_host(parsed_uri)

    # Raises a ValueError if the URI scheme is not 'matrix-federation' and the specified port is not the default port for the scheme.
    def test_scheme_not_matrix_federation_and_port_not_default(self):
        parsed_uri = urlparse(b"http://example.com:443")
        result = set_default_port_host(parsed_uri)
        assert result == b"example.com:443"


class TestAddHostHeaderPort:
    def test_adds_host_header_with_default_port(self):
        """
        Given a valid request_headers and parsed_uri, the function should add a host
        header with default port to the request_headers.
        """
        parsed_uri = create_parsed_uri("example.com", scheme="matrix-federation")
        request_headers = Headers()
        add_host_header_port(request_headers, parsed_uri)
        assert request_headers.getRawHeaders(b"host") == [b"example.com:8448"]

    def test_raises_exception_for_invalid_request_headers(self):
        """
        Given an invalid request_headers, the function should raise an exception.
        """
        request_headers = None
        parsed_uri = create_parsed_uri("example.com", scheme="matrix-federation")
        with pytest.raises(Exception):
            add_host_header_port(request_headers, parsed_uri)

    @pytest.mark.parametrize(
        "host, scheme, port, expected",
        [
            (
                "example.com",
                "matrix-federation",
                8448,
                b"example.com:8448",
            ),  # port specified
            (
                "example.com",
                "matrix-federation",
                None,
                b"example.com:8448",
            ),  # port not specified, default used
            (
                "example.com",
                "http",
                8080,
                b"example.com:8080",
            ),  # different scheme and port
        ],
    )
    def test_add_host_header_port(self, host, scheme, port, expected):
        """
        Given a valid request_headers and parsed_uri with a port specified,
        the function should not modify the host header.
        """
        request_headers = Headers()
        parsed_uri = create_parsed_uri(host, scheme=scheme, port=port)
        add_host_header_port(request_headers, parsed_uri)
        assert request_headers.getRawHeaders(b"host") == [expected]

    @pytest.mark.parametrize(
        "request_headers, parsed_uri",
        [
            (Headers(), None),  # invalid parsed_uri
            (
                None,
                create_parsed_uri("example.com", scheme="matrix-federation"),
            ),  # invalid request_headers
        ],
    )
    def test_raises_exception_for_invalid_inputs(self, request_headers, parsed_uri):
        """
        Given an invalid request_headers or parsed_uri, the function should raise an exception.
        """
        with pytest.raises(Exception):
            add_host_header_port(request_headers, parsed_uri)

    def test_does_not_modify_host_header_if_different_port_in_netloc_and_specified(
        self,
    ):
        """
        Given a valid request_headers and parsed_uri with a port specified in the
        netloc and a different default port specified, the function should not modify the host header.
        """
        request_headers = Headers()
        parsed_uri = create_parsed_uri(
            "example.com", scheme="matrix-federation", port=8000
        )
        add_host_header_port(request_headers, parsed_uri)
        assert request_headers.getRawHeaders(b"host") == [b"example.com:8000"]
