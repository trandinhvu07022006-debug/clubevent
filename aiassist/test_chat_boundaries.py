"""Regression tests for chat admission and internal-event context isolation."""
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TransactionTestCase
from django.urls import reverse

from .chatbot import HANDLERS, PRIVATE_INTENTS
from .models import AIInteractionLog
from .views import _reserve_ai_attempt


class ChatBudgetConcurrencyTests(SimpleTestCase):
    def test_atomic_reservations_share_one_budget(self):
        def reserve(_):
            request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.241")
            return _reserve_ai_attempt(request)

        with patch("aiassist.views.AI_LIMIT", 3):
            with ThreadPoolExecutor(max_workers=12) as workers:
                results = list(workers.map(reserve, range(24)))
        self.assertEqual(results.count(True), 3)


class ChatBoundaryTests(TransactionTestCase):
    def post_question(self, question, endpoint="chat_api"):
        return self.client.post(
            reverse("aiassist:" + endpoint),
            data=json.dumps({"question": question}),
            content_type="application/json",
        )

    def consume_stream(self, response):
        self.assertEqual(response.status_code, 200)
        try:
            data = b"".join(response.streaming_content).decode("utf-8")
        finally:
            response.close()
        return json.loads(data.strip().split("\n\n")[-1].removeprefix("data: "))

    @patch("aiassist.views.AI_LIMIT", 2)
    @patch("aiassist.chatbot._answer_with_ai", return_value=None)
    def test_failed_attempts_count_across_json_and_sse(self, provider):
        self.assertEqual(self.post_question("gửi xe ở đâu?").json()["source"], "rules")
        self.assertEqual(self.consume_stream(
            self.post_question("gửi xe ở đâu?", "chat_stream_api"))["source"], "rules")
        self.assertEqual(self.post_question("gửi xe ở đâu?").json()["source"], "rules")
        self.assertEqual(provider.call_count, 2)

    @patch("aiassist.views.AI_LIMIT", 1)
    @patch("aiassist.chatbot._answer_with_ai", return_value=None)
    def test_rule_and_blank_questions_do_not_reserve(self, provider):
        self.post_question("xin chào")
        self.consume_stream(self.post_question("", "chat_stream_api"))
        self.post_question("gửi xe ở đâu?")
        self.post_question("gửi xe ở đâu?")
        self.assertEqual(provider.call_count, 1)

    @patch("aiassist.views.AI_LIMIT", 1)
    @patch("aiassist.chatbot._answer_with_ai", return_value={
        "text": "Một câu trả lời.", "intent": "ai", "source": "ai",
        "links": [], "meta": {},
    })
    def test_abandoned_stream_still_consumes_reservation(self, provider):
        response = self.post_question("gửi xe ở đâu?", "chat_stream_api")
        self.assertEqual(response.status_code, 200)
        try:
            next(iter(response.streaming_content))
        finally:
            response.close()
        self.assertEqual(self.post_question("gửi xe ở đâu?").json()["source"], "rules")
        self.assertEqual(provider.call_count, 1)

    @patch("aiassist.chatbot._answer_with_ai", return_value=None)
    def test_legacy_session_history_is_not_forwarded(self, provider):
        session = self.client.session
        session["chat_history"] = [{"role": "assistant", "text": "INTERNAL-OLD"}]
        session.save()
        self.post_question("gửi xe ở đâu?")
        self.assertEqual(provider.call_args.kwargs["history"], [])
        self.assertNotIn("INTERNAL-OLD", str(self.client.session["chat_history"]))

    @patch("aiassist.chatbot._answer_with_ai", return_value=None)
    def test_internal_event_rule_answers_never_enter_history_or_logs(self, provider):
        self.assertTrue({"upcoming_events", "seats_left"} <= PRIVATE_INTENTS)
        sentinel = "INTERNAL-EVENT-SENTINEL"
        def private_result(user):
            return {"text": sentinel, "links": []}

        with patch.dict(HANDLERS, {
            "upcoming_events": private_result, "seats_left": private_result,
        }):
            self.assertEqual(self.post_question("Sắp tới có sự kiện gì?").json()["text"], sentinel)
            self.assertEqual(self.consume_stream(
                self.post_question("Còn vé không?", "chat_stream_api"))["text"], sentinel)

        self.assertNotIn(sentinel, str(self.client.session.get("chat_history", [])))
        self.assertFalse(AIInteractionLog.objects.filter(answer_preview__contains=sentinel).exists())
        self.post_question("gửi xe ở đâu?")
        self.assertNotIn(sentinel, str(provider.call_args.kwargs["history"]))
