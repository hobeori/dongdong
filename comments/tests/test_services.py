from unittest import mock

from django.test import SimpleTestCase, TestCase

from comments.models import CommentAnalysis
from comments.services import llm, pipeline, preprocess
from comments.services.errors import CompanyNotFound, LLMError


class PreprocessTests(SimpleTestCase):
    def test_clean_text_removes_special_and_jamo(self):
        self.assertEqual(preprocess.clean_text("1월 9일 14:27"), "1월 9일 1427")
        self.assertEqual(preprocess.clean_text("ㅋㅋㅋ 개미털기다 ㅠㅠ!!"), "개미털기다")

    def test_filter_by_rules(self):
        raw = ["364주", "5주", None, "", "   ", "ㅋㅋㅋㅋㅋㅋㅋ", "x" * 77,
               "20만갈꺼같음 19만에 정리할꺼임", "1월 9일 14:27"]
        self.assertEqual(
            preprocess.filter_by_rules(raw),
            ["20만갈꺼같음 19만에 정리할꺼임", "1월 9일 1427"],
        )

    def test_iqr_info(self):
        info = preprocess.iqr_info(["a" * n for n in (4, 8, 12, 16, 20)])
        self.assertEqual((info["q1"], info["q3"], info["iqr"]), (8, 16, 8))
        self.assertEqual(preprocess.iqr_info([])["max_len"], 76)


class LLMTests(SimpleTestCase):
    def test_parse_json_array_tolerates_noise(self):
        self.assertEqual(llm.parse_json_array('결과:\n```json\n[1, 3]\n```'), [1, 3])
        with self.assertRaises(LLMError):
            llm.parse_json_array("없음")

    def test_find_inappropriate_ignores_bad_indexes(self):
        with mock.patch.object(llm, "chat", return_value="[0, 5, \"a\"]"):
            self.assertEqual(llm.find_inappropriate(["a", "b"]), {0})

    def test_augment_length_mismatch(self):
        with mock.patch.object(llm, "chat", return_value='["only one"]'):
            with self.assertRaises(LLMError):
                llm.augment(["a", "b"])

    def test_missing_key(self):
        with self.settings(GMS_API_KEY=""):
            with self.assertRaises(LLMError):
                llm.chat("hi")


RAW = ["20만갈꺼같음 19만에 정리할꺼임", "364주", "욕설 댓글입니다 정말로", "조금씩 모아가는 마인드로 묻힌다"]


class PipelineTests(TestCase):
    def test_full_run_saves_all_stages(self):
        with mock.patch("comments.services.pipeline.crawler.crawl", return_value=("삼성전자", RAW)), \
             mock.patch.object(llm, "find_inappropriate", return_value={1}), \
             mock.patch.object(llm, "augment", side_effect=lambda c: [x + " 확장" for x in c]), \
             mock.patch.object(llm, "summarize", return_value="요약"):
            events = list(pipeline.run("삼성"))
        self.assertEqual(events[-1]["type"], "result")
        obj = CommentAnalysis.objects.get()
        self.assertEqual(obj.stock_name, "삼성전자")
        self.assertEqual(obj.raw_comments, RAW)
        self.assertEqual(len(obj.cleaned_comments), 2)  # 364주 제거, 부적절 1개 제거
        self.assertEqual(len(obj.final_comments), 4)
        self.assertEqual(obj.summary, "요약")

    def test_company_not_found_is_reported(self):
        with mock.patch("comments.services.pipeline.crawler.crawl", side_effect=CompanyNotFound("없음")):
            events = list(pipeline.run("zzz"))
        self.assertEqual(events[-1], {"type": "error", "message": "없음"})
        self.assertFalse(CommentAnalysis.objects.exists())

    def test_llm_failure_still_returns_crawled_data(self):
        with mock.patch("comments.services.pipeline.crawler.crawl", return_value=("삼성전자", RAW)), \
             mock.patch.object(llm, "chat", side_effect=LLMError("키 없음")):
            events = list(pipeline.run("삼성"))
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(len(events[-1]["warnings"]), 3)
        obj = CommentAnalysis.objects.get()
        self.assertEqual(obj.raw_comments, RAW)
        self.assertEqual(obj.augmented_comments, [])
