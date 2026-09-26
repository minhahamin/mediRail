from datetime import date

from app.prompts import calendar, system_prompt


def test_calendar_has_correct_weekdays():
    cal = calendar(date(2026, 9, 26), 3)  # 2026-09-26은 토요일
    assert cal == "2026-09-26(토), 2026-09-27(일), 2026-09-28(월)"


def test_prompt_contains_today_weekday_and_calendar():
    p = system_prompt("patient", today=date(2026, 9, 26))
    assert "토요일" in p and "2026-10-09(금)" in p and "환자" in p


def test_selected_patient_only_for_staff():
    assert "선택된 환자 id: 7" in system_prompt("doctor", 7)
    assert "선택된 환자" not in system_prompt("patient", 7)


def test_every_role_has_guide():
    for role in ("patient", "nurse", "doctor", "admin"):
        assert system_prompt(role)
