"""SKILL.md 로더와 스킬-도구-역할 정합성."""
import re

import pytest

from app import skills, tools
from app.prompts import system_prompt
from app.rbac import Role
from app.skills import SkillError, parse_skill

ROLES = [r.value for r in Role]


def test_all_skills_are_valid():
    found = skills.load_skills()
    assert set(found) == {"drug-interaction-check", "soap-note", "intake-summary", "medical-literature-qa", "emergency-triage"}
    for name, s in found.items():
        assert s.path.parent.name == name, "name은 디렉터리 이름과 같아야 한다"
        assert len(s.description) > 30 and s.body.startswith("#")
        assert set(s.roles) <= set(ROLES), f"{name}: 알 수 없는 역할"


def test_skill_tools_exist_and_are_available_to_its_roles():
    """스킬이 쓰라고 하는 도구는 등록돼 있어야 하고, 스킬을 받는 모든 역할이 그 도구를 실제로 가져야 한다."""
    for s in skills.load_skills().values():
        for t in s.tools:
            assert t in tools.TOOLS, f"{s.name}: 등록되지 않은 도구 {t}"
            for role in s.roles:
                assert t in {x.name for x in tools.tools_for(role)}, f"{s.name}: {role}는 {t} 도구가 없다"


@pytest.mark.parametrize("role", ROLES)
def test_skill_body_never_mentions_tools_the_role_lacks(role):
    """프롬프트가 역할에 없는 도구를 쓰라고 안내하면 LLM이 헛호출하거나 권한 우회를 시도한다."""
    prompt = system_prompt(role)
    available = {t.name for t in tools.tools_for(role)}
    mentioned = {t for t in tools.TOOLS if re.search(rf"\b{t}\b", prompt)}
    assert mentioned <= available, f"{role} 프롬프트가 사용 불가 도구를 언급: {mentioned - available}"


def test_prompt_contains_only_role_matching_skills():
    doctor, patient, admin = system_prompt("doctor"), system_prompt("patient"), system_prompt("admin")
    assert "## 스킬: soap-note" in doctor and "## 스킬: drug-interaction-check" in doctor and "## 스킬: medical-literature-qa" in doctor
    assert "## 스킬: drug-interaction-check" in patient
    assert "soap-note" not in patient and "medical-literature-qa" not in patient and "intake-summary" not in patient
    assert "절차 지식" not in admin                      # 원무에게는 스킬이 없다


def test_drug_skill_teaches_the_incident_lessons():
    body = skills.load_skills()["drug-interaction-check"].body
    for phrase in ("needs_confirmation", "not_listed", "안전하다·괜찮다고 단정하지 않는다", "약한 표현으로 바꾸지 않는다", "age_base"):
        assert phrase in body


def test_soap_skill_states_ai_only_drafts():
    body = skills.load_skills()["soap-note"].body
    assert "초안만" in body and "승인 도구는 존재하지 않는다" in body and "확진" in body


def test_parse_errors(tmp_path):
    bad = tmp_path / "SKILL.md"
    bad.write_text("# 제목만 있고 frontmatter가 없음", encoding="utf-8")
    with pytest.raises(SkillError, match="frontmatter"):
        parse_skill(bad)
    bad.write_text("---\nname: x\n---\n본문", encoding="utf-8")
    with pytest.raises(SkillError, match="description"):
        parse_skill(bad)


def test_parse_list_fields(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: t\ndescription: 설명 설명 설명\nroles: [doctor, nurse]\ntools: []\n---\n# 본문", encoding="utf-8")
    s = parse_skill(f)
    assert s.roles == ("doctor", "nurse") and s.tools == () and s.body == "# 본문"
