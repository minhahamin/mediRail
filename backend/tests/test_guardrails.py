import json
from pathlib import Path

import pytest

from app.guardrails import DISCLAIMER, check_output, detect_emergency, emergency_response

QS = [json.loads(l) for l in (Path(__file__).parents[2] / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("q", [q for q in QS if q.get("emergency")], ids=lambda q: q["id"])
def test_all_eval_emergency_questions_detected(q):
    assert detect_emergency(q["question"]), q["question"]


@pytest.mark.parametrize("q", [q for q in QS if not q.get("emergency") and q["role"] == "patient"], ids=lambda q: q["id"])
def test_no_false_positive_on_normal_patient_questions(q):
    assert detect_emergency(q["question"]) == [], q["question"]


def test_emergency_message_has_119_and_disclaimer():
    msg = emergency_response(["cardiac"])
    assert "119" in msg and DISCLAIMER in msg and "109" not in msg


def test_suicide_message_adds_109():
    msg = emergency_response(detect_emergency("요즘 죽고 싶다는 생각이 들어요"))
    assert "119" in msg and "109" in msg


def test_valid_citation_passes_and_disclaimer_added():
    r = check_output("일요일은 휴진입니다 [D1].", [{"id": "D1", "title": "클리닉 안내"}])
    assert r.events == ["disclaimer_added"] and r.text.endswith(DISCLAIMER) and "[D1]" in r.text


def test_fake_citation_replaced():
    r = check_output("140/90 이상입니다 [D9].", [{"id": "D1", "title": "x"}])
    assert "invalid_citation" in r.events and "[D9]" not in r.text


def test_forbidden_diagnosis_replaced():
    r = check_output("검사 결과 폐렴으로 확진입니다.", [])
    assert "forbidden_claim" in r.events and "확진" not in r.text


def test_uncited_answer_with_sources_gets_source_footer():
    r = check_output("내일 10시 예약이 있습니다.", [{"id": "D1", "title": "내 예약 목록"}])
    assert "uncited" in r.events and "[D1] 내 예약 목록" in r.text


def test_no_sources_no_footer():
    r = check_output("주호소: 인후통", [])
    assert r.events == ["disclaimer_added"]
