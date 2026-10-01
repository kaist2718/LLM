r"""
tests/test_question_bank.py — 질문 뱅크(REASONING_QUESTIONS.md)·채점표 생성 단위 테스트

실행:
  .venv\Scripts\python.exe -m unittest discover -s tests -v
  (또는 .venv\Scripts\python.exe tests\test_question_bank.py)
"""
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from run_questions import (  # noqa: E402
    AUTO_CHECK,
    KOREAN_SYSTEM,
    QUICK_IDS,
    auto_check,
    load_questions,
    write_outputs,
)


class TestQuestionBank(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.questions = load_questions(os.path.join(ROOT, "REASONING_QUESTIONS.md"))
        cls.by_id = {q["id"]: q for q in cls.questions}

    def test_questions_sorted_sequential(self):
        """문항 번호가 문서 순서와 일치하고 Q1부터 빠짐없이 이어져야 한다."""
        nums = [int(q["id"][1:]) for q in self.questions]
        self.assertEqual(nums, sorted(nums), "문항 번호가 오름차순이어야 합니다")
        self.assertEqual(nums, list(range(1, len(nums) + 1)), "Q1부터 연속 번호여야 합니다")

    def test_minimum_count(self):
        """A~G 추론 28문항 + H 재미있는 추론 6문항 이상."""
        self.assertGreaterEqual(len(self.questions), 34)
        self.assertGreaterEqual(len({q["category"] for q in self.questions}), 8)

    def test_required_fields(self):
        for q in self.questions:
            self.assertTrue(q["question"].strip(), f"{q['id']} 질문이 비어 있습니다")
            self.assertTrue(q["answer"].strip(), f"{q['id']} 정답 요지가 비어 있습니다")
            self.assertTrue(q["category"].strip(), f"{q['id']} 카테고리가 비어 있습니다")
            self.assertTrue(q["stars"].strip(), f"{q['id']} 난이도 표시가 비어 있습니다")

    def test_auto_check_covers_all_and_compiles(self):
        for q in self.questions:
            self.assertIn(q["id"], AUTO_CHECK, f"{q['id']} 자동 확인 키워드가 없습니다")
            for pat in AUTO_CHECK[q["id"]]:
                re.compile(pat)  # 정규식 컴파일 실패 시 예외

    def test_quick_ids_exist(self):
        for qid in QUICK_IDS:
            self.assertIn(qid, self.by_id, f"--quick 문항 {qid}가 질문 뱅크에 없습니다")

    def test_korean_forcing_system(self):
        """질문 뱅크 실행은 한국어 답변을 강제해야 한다."""
        self.assertIn("한국어", KOREAN_SYSTEM)

    def test_auto_check_marks(self):
        self.assertEqual(auto_check("Q3", "답은 정확히 100분입니다."), "✓")
        self.assertEqual(auto_check("Q3", "답은 500분입니다."), "✗")

    def test_write_outputs_smoke(self):
        """채점표(md/html/csv/json)가 빠짐없이 생성되는지 확인."""
        qs = self.questions[:2]
        results = [
            {"id": qs[0]["id"], "mode": "OFF", "run": 1, "thinking": False,
             "text": "테스트 답변 (100분)",
             "metrics": {"toks_per_s": 10.0, "elapsed_ms": 1000, "tokens": 5},
             "error": None, "auto": "✓", "wall_s": 1.0},
            {"id": qs[1]["id"], "mode": "ON", "run": 1, "thinking": True,
             "text": "테스트 답변",
             "metrics": {"toks_per_s": 8.0, "elapsed_ms": 2000, "tokens": 7},
             "error": None, "auto": "", "wall_s": 2.0},
        ]
        meta = {"model_key": "qwen35", "model_name": "Qwen3.5-9B", "device": "cpu",
                "temperature": 0.2, "max_tokens": 64, "runs": 1,
                "modes_text": "OFF/ON", "interrupted": False}
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_outputs(tmp, meta, qs, results)
            for key in ("md", "html", "csv", "json"):
                self.assertTrue(os.path.isfile(paths[key]), f"{key} 출력 파일이 없습니다")
            with open(paths["json"], encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data["results"]), 2)
            with open(paths["md"], encoding="utf-8") as f:
                md = f.read()
            self.assertIn(qs[0]["id"], md)
            self.assertIn(qs[1]["id"], md)
            with open(paths["html"], encoding="utf-8") as f:
                html_doc = f.read()
            self.assertIn("<html", html_doc.lower())


if __name__ == "__main__":
    unittest.main()
