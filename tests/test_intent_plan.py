import json
import time
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError

from ai import (
    AIAnalystError,
    AIProviderConfig,
    OpenAICompatibleClient,
    build_intent_messages,
    parse_intent_plan,
)


class TestIntentPlan(unittest.TestCase):
    @staticmethod
    def response(**updates):
        value = {
            "action": "targeted_scan",
            "topic": "purchase",
            "terms": ["purchase", "receipt", "entitlement"],
            "reply": "I will scan for purchase-related Boolean candidates.",
        }
        value.update(updates)
        return json.dumps(value)

    def test_parse_valid_targeted_scan_plan(self):
        plan = parse_intent_plan(self.response())
        self.assertEqual(plan.action, "targeted_scan")
        self.assertEqual(plan.topic, "purchase")
        self.assertEqual(plan.terms, ("purchase", "receipt", "entitlement"))

    def test_parse_clarify_plan(self):
        plan = parse_intent_plan(self.response(
            action="clarify", topic="", terms=[], reply="Which purchase behavior should I focus on?"
        ))
        self.assertEqual(plan.action, "clarify")
        self.assertEqual(plan.terms, ())

    def test_reject_invalid_json(self):
        with self.assertRaises(AIAnalystError):
            parse_intent_plan("not json")

    def test_reject_unknown_action_and_extra_keys(self):
        with self.assertRaises(AIAnalystError):
            parse_intent_plan(self.response(action="rename_function"))
        with self.assertRaises(AIAnalystError):
            parse_intent_plan(self.response(debug=True))

    def test_reject_oversized_terms(self):
        with self.assertRaises(AIAnalystError):
            parse_intent_plan(self.response(terms=["x"] * 17))
        with self.assertRaises(AIAnalystError):
            parse_intent_plan(self.response(terms=["x" * 65]))
        with self.assertRaises(AIAnalystError):
            parse_intent_plan(self.response(topic="x" * 81))
        with self.assertRaises(AIAnalystError):
            parse_intent_plan(self.response(reply="x" * 401))

    def test_history_is_limited_to_12_messages(self):
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
            for index in range(20)
        ]
        messages = build_intent_messages("double down on purchases", history)
        self.assertEqual(len(messages), 2)
        self.assertIn("turn-8", messages[1]["content"])
        self.assertNotIn("turn-7", messages[1]["content"])

    def test_intent_prompt_omits_binary_context(self):
        messages = build_intent_messages("double down on purchase related booleans", [])
        prompt = "\n".join(message["content"] for message in messages)
        self.assertNotIn("0x401000", prompt)
        self.assertNotIn("redeemPremiumReceipt", prompt)
        self.assertNotIn("HLIL", prompt)

    def test_empty_provider_content_raises_safe_error(self):
        payload = json.dumps({"choices": [{"message": {"content": "  "}}]})
        client = object.__new__(OpenAICompatibleClient)
        with self.assertRaisesRegex(AIAnalystError, "empty analysis"):
            client._parse_response(payload)

    def test_provider_timeout_has_upper_bound(self):
        config = AIProviderConfig(
            "https://provider.example/v1", "secret", "test-model", timeout_seconds=121
        )
        with self.assertRaisesRegex(AIAnalystError, "greater than 0 and at most 120 seconds"):
            config.validate()

    def test_oversized_provider_response_is_rejected(self):
        class FakeSocket:
            def settimeout(self, timeout):
                self.timeout = timeout

        class FakeBody:
            def __init__(self):
                self.raw = SimpleNamespace(_sock=FakeSocket())

            def read1(self, size):
                return b"x" * size

        class OversizedResponse:
            def __init__(self):
                self.fp = FakeBody()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read1(self, size):
                return self.fp.read1(size)

        config = AIProviderConfig("https://provider.example/v1", "secret", "test-model")
        client = OpenAICompatibleClient(config, opener=lambda *args, **kwargs: OversizedResponse())
        with self.assertRaisesRegex(AIAnalystError, "size limit"):
            client.analyze([])

    def test_http_error_body_read_is_capped(self):
        class FakeSocket:
            def settimeout(self, timeout):
                pass

        class ErrorBody:
            def __init__(self):
                self.raw = SimpleNamespace(_sock=FakeSocket())
                self.bytes_read = 0

            def read1(self, size):
                self.bytes_read += size
                return b"x" * size

            def close(self):
                pass

        body = ErrorBody()
        config = AIProviderConfig("https://provider.example/v1", "secret", "test-model")

        def fail_with_http_error(request, **kwargs):
            raise HTTPError(request.full_url, 500, "failure", {}, body)

        client = OpenAICompatibleClient(config, opener=fail_with_http_error)
        with self.assertRaisesRegex(AIAnalystError, "HTTP 500") as caught:
            client.analyze([])
        self.assertEqual(body.bytes_read, 4 * 1024)
        self.assertLess(len(str(caught.exception)), 1_100)

    def test_trickling_response_hits_total_deadline(self):
        class FakeSocket:
            def settimeout(self, timeout):
                self.timeout = timeout

        class SlowBody:
            def __init__(self):
                self.raw = SimpleNamespace(_sock=FakeSocket())

            def read1(self, size):
                delay = 0.03
                if self.raw._sock.timeout < delay:
                    time.sleep(self.raw._sock.timeout)
                    raise TimeoutError()
                time.sleep(delay)
                return b"x"

        class SlowResponse:
            def __init__(self):
                self.fp = SlowBody()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read1(self, size):
                return self.fp.read1(size)

        config = AIProviderConfig(
            "https://provider.example/v1", "secret", "test-model", timeout_seconds=0.05
        )
        client = OpenAICompatibleClient(config, opener=lambda *args, **kwargs: SlowResponse())
        with self.assertRaisesRegex(AIAnalystError, "timed out"):
            client.analyze([])


if __name__ == "__main__":
    unittest.main()
