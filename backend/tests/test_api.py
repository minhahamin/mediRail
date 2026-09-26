"""HTTP 레벨 RBAC 매트릭스와 /chat 엔드포인트."""
import pytest

from tests.conftest import login


@pytest.mark.parametrize("path", ["/patients", "/appointments", "/audit", "/soap/1", "/patients/1"])
def test_unauthenticated_is_401(client, path):
    assert client.get(path).status_code == 401


# (username, method, path) -> 기대 상태
MATRIX = [
    ("patient1", "GET", "/patients", 403),
    ("patient1", "GET", "/patients/1", 403),
    ("patient1", "GET", "/appointments", 200),
    ("patient1", "GET", "/appointments?patient_id=3", 403),
    ("patient1", "GET", "/audit", 403),
    ("nurse1", "GET", "/patients", 200),
    ("nurse1", "GET", "/patients/1/intake", 200),
    ("nurse1", "GET", "/soap/1", 403),
    ("nurse1", "GET", "/audit", 403),
    ("doctor1", "GET", "/patients/1", 200),
    ("doctor1", "GET", "/audit", 403),
    ("admin1", "GET", "/patients", 200),
    ("admin1", "GET", "/patients/1/intake", 403),   # 원무는 임상 정보 불가
    ("admin1", "GET", "/audit", 200),
    ("admin1", "GET", "/appointments", 200),
]


@pytest.mark.parametrize("user,method,path,expected", MATRIX)
def test_rbac_matrix(client, user, method, path, expected):
    r = client.request(method, path, headers=login(client, user))
    assert r.status_code == expected, r.text


def test_admin_profile_hides_clinical_fields(client):
    body = client.get("/patients/1", headers=login(client, "admin1")).json()
    assert "allergies" not in body and body["name"] == "김하늘"
    body = client.get("/patients/1", headers=login(client, "doctor1")).json()
    assert body["allergies"] == "페니실린"


def test_soap_approval_is_doctor_only(client):
    doc = login(client, "doctor1")
    # 초안은 서비스 계층(에이전트 도구)으로만 만들어지므로, 여기서는 존재하지 않는 노트로 권한 순서만 확인
    assert client.post("/soap/999/approve", headers=login(client, "nurse1")).status_code == 403
    assert client.post("/soap/999/approve", headers=doc).status_code == 404


def test_book_and_cancel_via_rest(client):
    h = login(client, "patient1")
    slots = client.get("/appointments/slots?date=2030-01-07", headers=h).json()["slots"]
    assert slots and slots[0] == "2030-01-07 09:00"
    r = client.post("/appointments", json={"slot": "2030-01-07 09:00", "reason": "상담"}, headers=h)
    assert r.status_code == 200, r.text
    assert client.post("/appointments", json={"slot": "2030-01-12 15:00"}, headers=h).status_code == 400  # 토요일 오후
    assert client.delete(f"/appointments/{r.json()['appointment_id']}", headers=h).status_code == 200


def test_chat_emergency_for_patient_never_reaches_llm(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM 호출 금지")
    monkeypatch.setattr("app.llm.chat", boom)
    r = client.post("/chat", json={"message": "숨쉬기가 너무 힘들고 입술이 파래져요"}, headers=login(client, "patient1"))
    assert r.status_code == 200 and "119" in r.json()["answer"] and r.json()["emergency"] == ["breathing"]


def test_chat_uses_configured_model_and_returns_sources(client, monkeypatch):
    seen = {}

    def fake(messages, tools=None, *, model=None):
        seen["n_tools"] = len(tools or [])
        seen["system"] = messages[0]["content"]
        if not any(m["role"] == "tool" for m in messages):
            tc = [{"id": "1", "type": "function", "function": {"name": "get_clinic_info", "arguments": "{}"}}]
            return {"message": {"role": "assistant", "content": None, "tool_calls": tc}, "usage": {}, "model": "qwen/qwen3.7-flash"}
        return {"message": {"role": "assistant", "content": "토요일은 13:00까지입니다 [D1]."}, "usage": {}, "model": "qwen/qwen3.7-flash"}

    monkeypatch.setattr("app.llm.chat", fake)
    r = client.post("/chat", json={"message": "토요일 진료시간은?"}, headers=login(client, "patient1")).json()
    assert r["sources"][0]["id"] == "D1" and r["model"] == "qwen/qwen3.7-flash" and "환자" in seen["system"]
    assert seen["n_tools"] == 6  # 환자 노출 도구: 안내, 슬롯, 예약목록, 예약, 취소, 문진접수


def test_chat_requires_auth(client):
    assert client.post("/chat", json={"message": "안녕"}).status_code == 401
