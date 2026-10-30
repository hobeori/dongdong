import json
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from comments.models import CommentAnalysis


def fake_run(name):
    obj = CommentAnalysis.objects.create(
        query_name=name, stock_name="삼성전자", raw_comments=["원본"],
        cleaned_comments=["정제"], augmented_comments=["증강"],
        iqr_info={"min_len": 5, "max_len": 76}, summary="요약문",
    )
    yield {"type": "progress", "message": "진행"}
    yield {"type": "result", "analysis": obj, "warnings": ["경고 예시"]}


class ViewTests(TestCase):
    def test_empty_name_does_nothing(self):
        with mock.patch("comments.views.pipeline.run") as run:
            for q in ("", "   "):
                resp = self.client.get(reverse("comments:company"), {"company_name": q})
                self.assertEqual(resp.status_code, 200)
        run.assert_not_called()

    def test_name_printed_and_results_rendered(self):
        with mock.patch("comments.views.pipeline.run", fake_run), \
             mock.patch("builtins.print") as printed:
            resp = self.client.get(reverse("comments:company"), {"company_name": "삼성"})
        printed.assert_called_with("삼성")
        self.assertContains(resp, "삼성전자 댓글 분석 결과")
        self.assertContains(resp, "요약문")

    def test_error_message_shown(self):
        def err(name):
            yield {"type": "error", "message": "검색 결과가 없습니다."}
        with mock.patch("comments.views.pipeline.run", err):
            resp = self.client.get(reverse("comments:company"), {"company_name": "zz"})
        self.assertContains(resp, "검색 결과가 없습니다.")

    def test_stream_ndjson(self):
        with mock.patch("comments.views.pipeline.run", fake_run):
            resp = self.client.get(reverse("comments:company_stream"), {"company_name": "삼성"})
            lines = [json.loads(l) for l in b"".join(resp.streaming_content).decode().splitlines()]
        self.assertEqual([l["type"] for l in lines], ["progress", "result"])
        self.assertIn("삼성전자 댓글 분석 결과", lines[1]["html"])

    def test_stream_empty_name_400(self):
        resp = self.client.get(reverse("comments:company_stream"))
        self.assertEqual(resp.status_code, 400)
