"""Adversarial contracts for the stdio MCP protocol boundary.

These tests exercise the real line-oriented server loop.  Every malformed-input
case is followed by a valid ping so rejecting one message is not considered
safe unless the same server process remains responsive.
"""

import io
import json
import re
import unittest
from unittest import mock

from charactercheck import engine, mcp, source


_MISSING = object()


def rpc(method, *, request_id=_MISSING, params=_MISSING):
    message = {"jsonrpc": "2.0", "method": method}
    if request_id is not _MISSING:
        message["id"] = request_id
    if params is not _MISSING:
        message["params"] = params
    return json.dumps(message, allow_nan=False)


def ping(request_id="continuation"):
    return rpc("ping", request_id=request_id)


def initialize(request_id, protocol_version=None):
    return rpc(
        "initialize",
        request_id=request_id,
        params={
            "protocolVersion": protocol_version or mcp.PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "boundary-test", "version": "1.0"},
        },
    )


def run_loop(*raw_messages):
    body = "".join(message.rstrip("\n") + "\n" for message in raw_messages)
    stdin, stdout, stderr = io.StringIO(body), io.StringIO(), io.StringIO()
    with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", stdout), \
            mock.patch("sys.stderr", stderr):
        mcp.main()
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()
                 if line.strip()]
    return responses, stdout.getvalue(), stderr.getvalue()


class MCPBoundaryCase(unittest.TestCase):
    def assert_ping(self, response, request_id="continuation"):
        self.assertEqual(response, {
            "jsonrpc": "2.0", "id": request_id, "result": {},
        })

    def assert_parse_failure_then_ping(self, malformed):
        responses, _stdout, _stderr = run_loop(malformed, ping())
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0], {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "parse error"},
        })
        self.assert_ping(responses[1])

    def assert_invalid_request_then_ping(self, message):
        responses, _stdout, _stderr = run_loop(message, ping())
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0], {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "invalid request"},
        })
        self.assert_ping(responses[1])


class TestStrictProtocolJSON(MCPBoundaryCase):
    def test_oversized_line_is_rejected_then_server_continues(self):
        oversized = "x" * 129
        with mock.patch.object(mcp, "MAX_REQUEST_BYTES", 128):
            responses, _stdout, _stderr = run_loop(oversized, ping())
        self.assertEqual(responses[0], {
            "jsonrpc": "2.0", "id": None,
            "error": {
                "code": -32600,
                "message": "request exceeds MCP size limit",
            },
        })
        self.assert_ping(responses[1])

    def test_deep_duplicate_nonfinite_and_huge_integer_fail_then_continue(self):
        deep = "[" * (source.MAX_DEPTH + 1) + "0" + "]" * (source.MAX_DEPTH + 1)
        duplicate = (
            '{"jsonrpc":"2.0","id":1,"method":"ping",'
            '"method":"tools/list"}'
        )
        nonfinite = '{"jsonrpc":"2.0","id":1,"method":"ping","x":NaN}'
        huge_integer = (
            '{"jsonrpc":"2.0","id":' +
            "9" * (source.MAX_NUMBER_TOKEN_LENGTH + 1) +
            ',"method":"ping"}'
        )
        for label, malformed in (
                ("deep", deep),
                ("duplicate", duplicate),
                ("nonfinite", nonfinite),
                ("huge_integer", huge_integer)):
            with self.subTest(case=label):
                self.assert_parse_failure_then_ping(malformed)

    def test_request_ids_are_exactly_string_or_non_boolean_integer(self):
        for valid in (0, -1, "request-1"):
            with self.subTest(valid=valid):
                responses, _stdout, _stderr = run_loop(ping(valid))
                self.assertEqual(len(responses), 1)
                self.assert_ping(responses[0], valid)

        for invalid in (None, True, 1.5, [], {}):
            with self.subTest(invalid=invalid):
                self.assert_invalid_request_then_ping(ping(invalid))

    def test_valid_notifications_never_receive_a_response(self):
        responses, _stdout, _stderr = run_loop(
            rpc("ping"),
            rpc("notifications/initialized"),
            rpc("tools/list", params={}),
            rpc("unknown/notification"),
            ping(),
        )
        self.assertEqual(len(responses), 1)
        self.assert_ping(responses[0])


class TestLifecycleAndMethods(MCPBoundaryCase):
    def test_initialize_negotiates_supported_and_unknown_versions(self):
        responses, _stdout, _stderr = run_loop(
            initialize(1),
            initialize(2, "1900-01-01"),
        )
        self.assertEqual(len(responses), 2)
        for request_id, response in enumerate(responses, 1):
            self.assertEqual(response["id"], request_id)
            result = response["result"]
            self.assertEqual(result["protocolVersion"], mcp.PROTOCOL_VERSION)
            self.assertEqual(result["capabilities"], {
                "tools": {"listChanged": False},
            })
            self.assertEqual(result["serverInfo"]["name"], "charactercheck")
            self.assertIsInstance(result["serverInfo"]["version"], str)
            self.assertTrue(result["instructions"])

    def test_invalid_initialize_params_are_typed_and_loop_continues(self):
        invalid_params = (
            _MISSING,
            [],
            {"protocolVersion": 1, "capabilities": {},
             "clientInfo": {"name": "x", "version": "1"}},
            {"protocolVersion": mcp.PROTOCOL_VERSION, "capabilities": [],
             "clientInfo": {"name": "x", "version": "1"}},
            {"protocolVersion": mcp.PROTOCOL_VERSION, "capabilities": {}},
            {"protocolVersion": mcp.PROTOCOL_VERSION, "capabilities": {},
             "clientInfo": {"name": 1, "version": "1"}},
            {"protocolVersion": mcp.PROTOCOL_VERSION, "capabilities": {},
             "clientInfo": {"name": "x"}},
        )
        for index, params in enumerate(invalid_params):
            with self.subTest(case=index):
                message = rpc("initialize", request_id=1, params=params) \
                    if params is not _MISSING else rpc("initialize", request_id=1)
                responses, _stdout, _stderr = run_loop(message, ping())
                self.assertEqual(len(responses), 2)
                self.assertEqual(responses[0], {
                    "jsonrpc": "2.0", "id": 1,
                    "error": {"code": -32602, "message": "invalid params"},
                })
                self.assert_ping(responses[1])

    def test_ping_and_invalid_ping_params(self):
        responses, _stdout, _stderr = run_loop(
            rpc("ping", request_id=1),
            rpc("ping", request_id="two", params={}),
            rpc("ping", request_id=3, params=[]),
            ping(),
        )
        self.assertEqual(responses[0], {
            "jsonrpc": "2.0", "id": 1, "result": {},
        })
        self.assertEqual(responses[1], {
            "jsonrpc": "2.0", "id": "two", "result": {},
        })
        self.assertEqual(responses[2], {
            "jsonrpc": "2.0", "id": 3,
            "error": {"code": -32602, "message": "invalid params"},
        })
        self.assert_ping(responses[3])

    def test_unknown_method_error_is_static_and_redacted(self):
        secret = "unknown/SECRET_/private/table.json?token=do-not-emit"
        responses, stdout, stderr = run_loop(
            rpc(secret, request_id=7), ping(),
        )
        self.assertEqual(responses[0], {
            "jsonrpc": "2.0", "id": 7,
            "error": {"code": -32601, "message": "method not found"},
        })
        self.assertNotIn(secret, stdout + stderr)
        self.assert_ping(responses[1])


class TestToolContracts(MCPBoundaryCase):
    def test_tool_schemas_are_closed_structured_and_read_only(self):
        responses, _stdout, _stderr = run_loop(
            rpc("tools/list", request_id=1, params={}),
        )
        advertised = responses[0]["result"]["tools"]
        self.assertEqual(advertised, mcp.TOOLS)
        self.assertEqual(len({tool["name"] for tool in advertised}),
                         len(advertised))
        for tool in advertised:
            with self.subTest(tool=tool["name"]):
                input_schema = tool["inputSchema"]
                self.assertEqual(input_schema["type"], "object")
                self.assertIs(input_schema["additionalProperties"], False)
                self.assertLessEqual(set(input_schema.get("required", [])),
                                     set(input_schema.get("properties", {})))
                self.assertEqual(tool["outputSchema"]["type"], "object")
                annotations = tool["annotations"]
                self.assertIs(annotations["readOnlyHint"], True)
                self.assertIs(annotations["destructiveHint"], False)
                self.assertIsInstance(annotations["idempotentHint"], bool)
                self.assertIsInstance(annotations["openWorldHint"], bool)
                self.assertEqual(annotations["idempotentHint"],
                                 tool["name"] == "selftest")
                self.assertEqual(annotations["openWorldHint"],
                                 tool["name"] != "selftest")

    def test_wrong_extra_and_missing_tool_arguments_never_execute(self):
        invalid_calls = (
            ("qa full string", "qa", {"ref": "12345", "full": "false"}),
            ("qa full integer", "qa", {"ref": "12345", "full": 0}),
            ("missing ref", "qa", {"full": False}),
            ("wrong ref type", "derive", {"ref": 12345}),
            ("boolean ref", "derive", {"ref": True}),
            ("extra role assertion", "seatpack",
             {"ref": "12345", "for_dm": True}),
            ("extra persona assertion", "snapshot",
             {"ref": "12345", "include_persona": True}),
            ("wrong baseline type", "diff",
             {"ref": "12345", "baseline": []}),
        )
        for label, tool_name, arguments in invalid_calls:
            with self.subTest(case=label), \
                    mock.patch.object(mcp, "_call") as call:
                request = rpc(
                    "tools/call",
                    request_id=1,
                    params={"name": tool_name, "arguments": arguments},
                )
                responses, _stdout, _stderr = run_loop(request, ping())
                call.assert_not_called()
                self.assertEqual(responses[0], {
                    "jsonrpc": "2.0", "id": 1,
                    "error": {
                        "code": -32602,
                        "message": "invalid tool arguments",
                    },
                })
                self.assert_ping(responses[1])

    def test_boolean_false_is_accepted_for_qa_full(self):
        request = rpc(
            "tools/call",
            request_id=1,
            params={
                "name": "qa",
                "arguments": {"ref": "12345", "full": False},
            },
        )
        with mock.patch.object(mcp, "_call", return_value={"ok": True}) as call:
            responses, _stdout, _stderr = run_loop(request)
        call.assert_called_once_with(
            "qa", {"ref": "12345", "full": False})
        self.assertEqual(responses[0]["result"]["structuredContent"],
                         {"ok": True})

    def test_oversized_tool_result_is_typed_and_loop_continues(self):
        request = rpc(
            "tools/call",
            request_id=1,
            params={"name": "selftest", "arguments": {}},
        )
        with mock.patch.object(mcp, "MAX_RESPONSE_BYTES", 128), \
                mock.patch.object(mcp, "_call",
                                  return_value={"payload": "x" * 129}):
            responses, _stdout, _stderr = run_loop(request, ping())
        failure = responses[0]["result"]
        self.assertIs(failure["isError"], True)
        self.assertEqual(failure["structuredContent"]["error"],
                         "output_too_large")
        self.assertIs(failure["structuredContent"]["retryable"], False)
        self.assert_ping(responses[1])


class TestBootstrapFailureRedaction(MCPBoundaryCase):
    def _tool_request(self, name, request_id=1):
        return rpc(
            "tools/call",
            request_id=request_id,
            params={"name": name, "arguments": {}},
        )

    def test_doctor_dns_and_network_failures_do_not_emit_exception_text(self):
        secret = "SECRET_/private/table.json?proxy_token=do-not-emit"

        with mock.patch("socket.getaddrinfo", side_effect=OSError(secret)):
            responses, stdout, stderr = run_loop(
                self._tool_request("doctor"), ping(),
            )
        self.assertNotIn(secret, stdout + stderr)
        checks = responses[0]["result"]["structuredContent"]["checks"]
        self.assertEqual(next(check for check in checks
                              if check["check"] == "dns")["ok"], False)
        self.assert_ping(responses[1])

        with mock.patch("socket.getaddrinfo", return_value=[]), \
                mock.patch("urllib.request.urlopen",
                           side_effect=OSError(secret)):
            responses, stdout, stderr = run_loop(
                self._tool_request("doctor"), ping(),
            )
        self.assertNotIn(secret, stdout + stderr)
        checks = responses[0]["result"]["structuredContent"]["checks"]
        self.assertEqual(next(check for check in checks
                              if check["check"] == "network")["ok"], False)
        self.assert_ping(responses[1])

    def test_selftest_handled_failure_does_not_emit_exception_text(self):
        secret = "SECRET_/private/table.json?token=do-not-emit"
        with mock.patch.object(engine, "derive", side_effect=RuntimeError(secret)):
            responses, stdout, stderr = run_loop(
                self._tool_request("selftest"), ping(),
            )
        self.assertNotIn(secret, stdout + stderr)
        result = responses[0]["result"]["structuredContent"]
        self.assertFalse(result["ok"])
        self.assertIn("RuntimeError", result["report"])
        self.assert_ping(responses[1])

    def test_unexpected_bootstrap_failures_are_redacted_and_loop_continues(self):
        secret = "SECRET_/private/table.json?token=do-not-emit"
        for tool_name, function_name in (("doctor", "doctor"),
                                         ("selftest", "selftest")):
            with self.subTest(tool=tool_name), \
                    mock.patch.object(
                        mcp.errors, function_name,
                        side_effect=RuntimeError(secret)):
                responses, stdout, stderr = run_loop(
                    self._tool_request(tool_name), ping(),
                )
                self.assertNotIn(secret, stdout + stderr)
                failure = responses[0]
                self.assertEqual(failure["error"]["code"], -32603)
                data = failure["error"]["data"]
                self.assertEqual(data["error"], "internal_error")
                self.assertRegex(data["correlation_id"], r"^[0-9a-f]{16}$")
                self.assertIn(data["correlation_id"], stderr)
                self.assertRegex(stderr, re.compile(r"exception=RuntimeError"))
                self.assert_ping(responses[1])


if __name__ == "__main__":
    unittest.main()
