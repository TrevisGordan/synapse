from typing import Any, Dict, Generator
from unittest.mock import ANY, Mock, create_autospec

from netaddr import IPSet
from parameterized import parameterized

from twisted.internet import defer
from twisted.internet.defer import Deferred, TimeoutError
from twisted.internet.error import ConnectingCancelledError, DNSLookupError
from twisted.test.proto_helpers import MemoryReactor, StringTransport
from twisted.web.client import Agent, ResponseNeverReceived
from twisted.web.http import HTTPChannel
from twisted.web.http_headers import Headers

from synapse.api.errors import HttpResponseException, RequestSendFailed
from synapse.config._base import ConfigError
from synapse.http.matrixfederationclient import (
    ByteParser,
    MatrixFederationHttpClient,
    MatrixFederationRequest,
)
from synapse.logging.context import (
    SENTINEL_CONTEXT,
    LoggingContext,
    LoggingContextOrSentinel,
    current_context,
)
from synapse.server import HomeServer
from synapse.util import Clock

from tests.replication._base import BaseMultiWorkerStreamTestCase
from tests.server import FakeTransport
from tests.test_utils import FakeResponse
from tests.unittest import HomeserverTestCase, override_config




# from ..federation.test_matrix_federation_agent import MatrixFederationAgentTests


from twisted.trial import unittest



class CalculationTestCase(unittest.TestCase):
    def setUp(self):

        ...

    def test_add(self):
        result, expected = 1, 1
        self.assertEqual(result, expected)



# MatrixFederationAgentTests.test_get_ip_address.skip = "SKIP THIS"
