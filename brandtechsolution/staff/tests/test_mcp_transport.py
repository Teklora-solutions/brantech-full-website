"""Regression coverage for MCP connections on broken dual-stack networks."""

import io
import json
import socket
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts import teklora_mcp as mcp


IPV6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0))
IPV4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))


class MCPTransportTests(TestCase):
    @patch.object(mcp.socket, "getaddrinfo", return_value=[IPV6, IPV4])
    @patch.object(mcp.socket, "socket")
    def test_unreachable_ipv6_falls_back_and_restores_io_timeout(self, factory, resolver):
        ipv6, ipv4 = Mock(), Mock()
        ipv6.connect.side_effect = TimeoutError("IPv6 unreachable")
        factory.side_effect = [ipv6, ipv4]
        self.assertIs(mcp._connect_with_fallback(("example.test", 443)), ipv4)
        ipv6.settimeout.assert_called_once_with(3)
        ipv6.close.assert_called_once()
        ipv4.connect.assert_called_once_with(IPV4[4])
        self.assertEqual(ipv4.settimeout.call_args_list[-1].args, (30,))
        ipv4.close.assert_not_called()

    @patch.object(mcp.socket, "getaddrinfo", return_value=[IPV6, IPV4])
    @patch.object(mcp.socket, "socket")
    def test_working_ipv6_is_not_disabled(self, factory, resolver):
        self.assertIs(mcp._connect_with_fallback(("example.test", 443)), factory.return_value)
        factory.assert_called_once_with(*IPV6[:3])

    @patch.object(mcp.socket, "getaddrinfo", return_value=[IPV6, IPV4])
    @patch.object(mcp.socket, "socket")
    @patch.object(mcp.time, "monotonic", side_effect=[0, 0, 11])
    def test_shared_budget_stops_further_connection_attempts(self, clock, factory, resolver):
        factory.return_value.connect.side_effect = TimeoutError("unreachable")
        with self.assertRaisesRegex(TimeoutError, "budget exhausted"):
            mcp._connect_with_fallback(("example.test", 443))
        factory.assert_called_once()
        factory.return_value.close.assert_called_once()

    @patch.object(mcp.socket, "getaddrinfo", return_value=[IPV4])
    @patch.object(mcp.socket, "socket")
    def test_last_error_propagates_and_failed_socket_closes(self, factory, resolver):
        factory.return_value.connect.side_effect = ConnectionRefusedError("refused")
        with self.assertRaises(ConnectionRefusedError):
            mcp._connect_with_fallback(("example.test", 443), timeout=1)
        factory.return_value.settimeout.assert_called_once_with(1)
        factory.return_value.close.assert_called_once()

    def test_http_and_https_use_local_factory_with_tls_verification(self):
        client = mcp.TekloraClient("https://example.test", "test-key")
        self.assertTrue(any(isinstance(h, mcp._HTTPHandler) for h in client.opener.handlers))
        handler = next(h for h in client.opener.handlers if isinstance(h, mcp._HTTPSHandler))
        with patch.object(handler, "do_open") as do_open:
            handler.https_open(Mock())
        self.assertIs(do_open.call_args.args[0], mcp._HTTPSConnection)
        connection = mcp._HTTPSConnection("example.test")
        self.assertTrue(connection._context.check_hostname)
        self.assertIs(connection._create_connection, mcp._connect_with_fallback)
        self.assertIs(mcp._HTTPConnection("example.test")._create_connection, mcp._connect_with_fallback)

    def test_timeout_becomes_explicit_stdio_tool_error(self):
        client = mcp.TekloraClient("https://example.test", "test-key")
        request = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "teklora_get_developer_profile", "arguments": {},
        }}
        output = io.StringIO()
        with patch.object(client.opener, "open", side_effect=TimeoutError("stalled")), \
                patch.object(mcp.sys, "stdin", io.StringIO(json.dumps(request) + "\n")), \
                patch.object(mcp.sys, "stdout", output):
            mcp.run_stdio_server(client)
        response = json.loads(output.getvalue())
        self.assertEqual(response["id"], 7)
        self.assertTrue(response["result"]["isError"])
        self.assertIn("timed out", response["result"]["content"][0]["text"])
        self.assertNotIn("test-key", output.getvalue())
