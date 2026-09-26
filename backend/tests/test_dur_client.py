"""식약처 DUR 성분정보 클라이언트: 실제 API의 특성을 흉내 낸 모의 서버로 검증.

재현하는 특성: {"item": {...}} 래퍼, 삭제된 고시(DEL_YN), 한쪽 방향으로만 등재된 쌍, numOfRows>500이면 빈 응답,
XML/JSON(HTTP 400) 오류 형식, 품목명 끝 괄호의 성분명.
"""
import httpx
import pytest

from mcp_servers.mfds_dur import server
from mcp_servers.mfds_dur.client import NOTICE, DurClient, DurError, name_match

KEY_ENCODED = "abc%2Bdef%2F123%3D%3D"
KEY_DECODED = "abc+def/123=="


def pair(a, a_eng, a_code, b, b_eng, b_code, reason, date="20090303", del_yn="정상"):
    return {"TYPE_NAME": "병용금기", "INGR_CODE": a_code, "INGR_KOR_NAME": a, "INGR_ENG_NAME": a_eng,
            "MIXTURE_INGR_CODE": b_code, "MIXTURE_INGR_KOR_NAME": b, "MIXTURE_INGR_ENG_NAME": b_eng,
            "NOTIFICATION_DATE": date, "PROHBT_CONTENT": reason, "REMARK": None, "DEL_YN": del_yn}


def build_pairs():
    rows = [
        pair("클래리트로마이신", "Clarithromycin", "D0C", "심바스타틴", "Simvastatin", "D0S", "근병증, 횡문근융해의 위험증가"),   # 한쪽 방향으로만 등재
        pair("클래리트로마이신", "Clarithromycin", "D0C", "심바스타틴", "Simvastatin", "D0S", "횡문근융해증 보고", "20231220"),
        pair("이트라코나졸", "Itraconazole", "D0I", "심바스타틴", "Simvastatin", "D0S", "횡문근융해증"),
        pair("니트로글리세린", "Nitroglycerin", "D0N", "실데나필", "Sildenafil", "D0D", "혈압강하작용 증가", "20080401"),
        pair("니코란딜", "Nicorandil", "D0R", "실데나필", "Sildenafil", "D0D", "혈압강하작용 증가"),
        pair("메나테트레논", "Menatetrenone", "D0M", "와파린", "Warfarin", "D0W", "와파린 효과 감소"),
        pair("아스피린", "Aspirin", "D0A", "메토트렉세이트", "Methotrexate", "D0X", "독성 증가"),
        pair("사이클로스포린", "Cyclosporine", "D0Y", "로수바스타틴", "Rosuvastatin", "D0U", "근병증 위험 증가"),   # 로바스타틴과 표기가 비슷한 '다른 약'
        pair("사이클로스포린", "Cyclosporine", "D0Y", "심바스타틴", "Simvastatin", "D0S", "횡문근융해 위험성 증가"),
        # 삭제된 고시: 결과에 절대 나오면 안 된다
        pair("와파린", "Warfarin", "D0W", "아스피린", "Aspirin", "D0A", "(삭제된 항목) 출혈", del_yn="삭제"),
    ]
    for i in range(1300):   # 1300+행 → 3페이지 (페이징 검증)
        rows.append(pair(f"가상성분{i}", f"Virtual{i}", f"V{i:04d}", f"가상상대{i}", f"Partner{i}", f"P{i:04d}", "가상 사유"))
    return rows


def single(cat, name, eng, code, **extra):
    return {"TYPE_NAME": cat, "INGR_CODE": code, "INGR_NAME": name, "INGR_ENG_NAME": eng, "PROHBT_CONTENT": None, "REMARK": None,
            "DEL_YN": "정상", **extra}


SINGLES = {
    "getPwnmTabooInfoList02": [single("임부금기", "아스피린", "Aspirin", "D0A", PROHBT_CONTENT="임신 3기 동맥관 조기 폐쇄 가능", GRADE="1등급"),
                              single("임부금기", "졸피뎀타르타르산염", "Zolpidem", "D0Z", PROHBT_CONTENT="신생아 금단 증상", GRADE="3등급"),
                              single("임부금기", "삭제된약", "Deleted", "D0Q", PROHBT_CONTENT="삭제", DEL_YN="삭제")],
    "getSpcifyAgrdeTabooInfoList02": [single("특정연령대금기", "졸피뎀타르타르산염", "Zolpidem", "D0Z", PROHBT_CONTENT="안전성 및 유효성 미확립", AGE_BASE="18세 이하")],
    "getOdsnAtentInfoList02": [single("노인주의", "클로르디아제폭시드", "Chlordiazepoxide", "D0L", PROHBT_CONTENT="소량부터 신중투여")],
    "getCpctyAtentInfoList02": [single("용량주의", "졸피뎀타르타르산염", "Zolpidem", "D0Z", MAX_QTY="10밀리그램")],
    "getMdctnPdAtentInfoList02": [single("투여기간주의", "졸피뎀타르타르산염", "Zolpidem", "D0Z", MAX_DOSAGE_TERM="4주")],
}
PRODUCTS = [{"ITEM_SEQ": "1", "ITEM_NAME": "타이레놀정500밀리그람(아세트아미노펜)"},
            {"ITEM_SEQ": "2", "ITEM_NAME": "리피토정20밀리그램(아토르바스타틴칼슘삼수화물)"},
            {"ITEM_SEQ": "3", "ITEM_NAME": "심바스타정20밀리그램(심바스타틴)"}]


class FakeDur:
    def __init__(self, page_drop=False, error=None, pairs=None):
        self.pairs, self.calls, self.page_drop, self.error = pairs or build_pairs(), [], page_drop, error

    def __call__(self, req: httpx.Request) -> httpx.Response:
        p, op = dict(req.url.params), req.url.path.rsplit("/", 1)[-1]
        self.calls.append((op, p))
        if self.error:
            return self.error
        if op == "getDurPrdlstInfoList03":
            rows = [r for r in PRODUCTS if p.get("itemName", "") in r["ITEM_NAME"]]
        elif op == "getUsjntTabooInfoList02":
            rows = self.pairs
        else:
            rows = SINGLES.get(op, [])
        n, page = int(p["numOfRows"]), int(p["pageNo"])
        if n > 500:   # 실제 API: 오류 없이 totalCount조차 없는 빈 본문
            return httpx.Response(200, json={"header": {"resultCode": "00"}, "body": {"pageNo": page, "numOfRows": n}})
        chunk = rows[(page - 1) * n: page * n]
        if self.page_drop and page == 2:
            chunk = chunk[:10]
        body = {"pageNo": page, "totalCount": len(rows), "numOfRows": n}
        if chunk:
            body["items"] = [{"item": r} for r in chunk]   # 실제 응답의 래퍼 형식
        return httpx.Response(200, json={"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": body})


def make(api=None, key=KEY_ENCODED, cache_path=None, **kw):
    api = api or FakeDur()
    return DurClient(key, http=httpx.Client(transport=httpx.MockTransport(api)), cache_path=cache_path, **kw), api


# ---------- 키/요청 ----------
def test_encoded_key_is_decoded_once():
    c, api = make()
    c.check_interaction("심바스타틴", "클래리트로마이신")
    assert api.calls[0][1]["serviceKey"] == KEY_DECODED


def test_missing_key_is_reported():
    with pytest.raises(DurError, match="DATA_GO_KR_API_KEY"):
        DurClient(None)


def test_page_size_never_exceeds_limit():
    c, api = make()
    c.check_interaction("심바스타틴", "클래리트로마이신")
    assert all(int(p["numOfRows"]) <= 500 for _, p in api.calls)


def test_uses_ingredient_service_operations():
    c, api = make()
    c.check_interaction("심바스타틴", "클래리트로마이신")
    assert {op for op, _ in api.calls} == {"getUsjntTabooInfoList02"}       # 품목서비스(79만 행)를 조회하지 않는다


def test_full_dataset_is_fetched_once_with_paging():
    c, api = make()
    c.check_interaction("심바스타틴", "클래리트로마이신")
    assert sorted(int(p["pageNo"]) for _, p in api.calls) == [1, 2, 3]     # 1300+행 = 3페이지, 이후 조회는 API 호출 없음
    n = len(api.calls)
    c.check_interaction("이트라코나졸", "심바스타틴")
    c.check_interaction("니트로글리세린", "실데나필")
    assert len(api.calls) == n


# ---------- 병용금기 ----------
def test_contraindicated_with_reasons_and_notice():
    r = make()[0].check_interaction("심바스타틴", "클래리트로마이신")
    assert r["status"] == "contraindicated" and r["notice"] == NOTICE and r["match_type"] == "exact"
    assert {x["reason"] for x in r["contraindications"]} == {"근병증, 횡문근융해의 위험증가", "횡문근융해증 보고"}
    assert r["refs"][0].startswith("DUR:병용금기:")


def test_search_is_bidirectional():
    """쌍은 한쪽 방향으로만 등재돼 있어도(클래리트로마이신→심바스타틴) 어느 순서로 물어도 찾아야 한다."""
    c = make()[0]
    assert c.check_interaction("심바스타틴", "클래리트로마이신")["status"] == "contraindicated"
    assert c.check_interaction("클래리트로마이신", "심바스타틴")["status"] == "contraindicated"


def test_deleted_notices_are_excluded():
    """삭제된 고시(와파린×아스피린)는 결과에 나오면 안 된다. 와파린은 다른 쌍으로 등재돼 있으므로 '해석은 됨 + 금기 없음'이어야 한다."""
    r = make()[0].check_interaction("와파린", "아스피린")
    assert r["status"] == "not_listed" and r["contraindications"] == []
    assert r["in_dur_list"] == {"와파린": True, "아스피린": True}
    assert "안전하다는 뜻은 아닙니다" in r["hint"] and r["notice"] == NOTICE


def test_english_names_match():
    assert make()[0].check_interaction("simvastatin", "clarithromycin")["status"] == "contraindicated"


def test_spelling_variant_is_surfaced_for_confirmation_not_missed():
    """실제 사고 재현: LLM이 '클라리스로마이신'(DUR 표기는 클래리트로마이신)으로 호출. 놓치면 금기를 '금기 아님'으로 안내하게 된다.
    다만 유사도만으로는 다른 약과 구분할 수 없으므로 확정하지 않고 needs_confirmation으로 결과와 후보를 함께 준다."""
    r = make()[0].check_interaction("심바스타틴", "클라리스로마이신")
    assert r["status"] == "needs_confirmation" and r["match_type"] == "similar_spelling"
    assert r["confirm"] == [{"input": "클라리스로마이신", "candidates": ["클래리트로마이신"]}]
    assert r["contraindications"] and "같은 성분" in r["match_note"] and "다른 약이면" in r["match_note"]


def test_confirmed_by_requerying_with_the_exact_name():
    assert make()[0].check_interaction("심바스타틴", "클래리트로마이신")["status"] == "contraindicated"


def test_similar_but_different_drug_is_never_asserted_as_contraindicated():
    """로바스타틴 ≠ 로수바스타틴 (자모 유사도 0.92). 로수바스타틴의 금기를 로바스타틴의 금기로 단정하면 안 된다."""
    r = make()[0].check_interaction("로바스타틴", "사이클로스포린")
    assert r["status"] == "needs_confirmation" and r["status"] != "contraindicated"
    assert r["confirm"][0]["candidates"] == ["로수바스타틴"]


def test_similar_candidate_without_any_pair_is_reported_as_did_you_mean():
    r = make()[0].check_interaction("로바스타틴", "아스피린")
    assert r["status"] == "not_listed" and r["did_you_mean"][0]["candidates"] == ["로수바스타틴"]


def test_different_drugs_are_not_fuzzy_matched():
    r = make()[0].check_interaction("심바스타틴", "케토코나졸")
    assert r["status"] == "not_listed" and r["unresolved"] == ["케토코나졸"]


def test_partial_match_is_flagged():
    r = make()[0].check_interaction("심바스타틴", "클래리트로마이신제피과립")   # 제형 접미사
    assert r["status"] == "contraindicated" and r["match_type"] == "partial" and "일부만 일치" in r["match_note"]


def test_unresolved_side_returns_partner_list_for_class_name_retry():
    """'질산염'은 DUR에 없는 이름이지만, 실데나필의 병용금기 성분 목록에 니트로글리세린이 있어 LLM이 계열로 이어갈 수 있다."""
    r = make()[0].check_interaction("실데나필", "질산염")
    assert r["status"] == "not_listed" and r["unresolved"] == ["질산염"]
    assert r["listed_partners"]["of"] == "실데나필" and "니트로글리세린" in r["listed_partners"]["names"]
    assert "병용금기로 고시된 성분 전체" in r["listed_partners"]["meaning"]


def test_both_resolved_no_partner_list_needed():
    r = make()[0].check_interaction("아스피린", "니코란딜")
    assert r["status"] == "not_listed" and "listed_partners" not in r and "unresolved" not in r


def test_both_unresolved():
    r = make()[0].check_interaction("가짜약A", "가짜약B")
    assert r["status"] == "unresolved" and r["notice"] == NOTICE


def test_brand_name_is_converted_to_ingredient():
    """상품명은 품목서비스로 성분을 찾아 변환한다: 심바스타정(심바스타틴) → 심바스타틴."""
    c, api = make()
    r = c.check_interaction("심바스타정", "클래리트로마이신")
    assert r["status"] == "contraindicated" and r["drug_a"]["via"] == "품목명 '심바스타정' → 성분 '심바스타틴'"
    assert any(op == "getDurPrdlstInfoList03" for op, _ in api.calls)


def test_brand_with_unknown_ingredient_stays_unresolved():
    r = make()[0].check_interaction("타이레놀", "심바스타틴")   # 아세트아미노펜은 DUR 병용금기 목록에 없는 성분
    assert r["status"] == "not_listed" and r["unresolved"] == ["타이레놀"]


# ---------- 안정성 ----------
def test_truncated_pages_are_rejected_not_silently_accepted():
    with pytest.raises(DurError, match="불완전"):
        make(FakeDur(page_drop=True))[0].check_interaction("심바스타틴", "클래리트로마이신")


@pytest.mark.parametrize("resp,expected", [
    (httpx.Response(200, text="<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE KEY IS NOT REGISTERED ERROR.</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>"), "등록되지 않았"),
    (httpx.Response(200, text="<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>"), "한도"),
    (httpx.Response(400, json={"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "NO_OPENAPI_SERVICE_ERROR", "returnAuthMsg": "해당 오픈API 서비스가 없거나 폐기됨"}}}), "서비스를 찾을 수 없습니다"),
])
def test_api_errors_become_readable_messages_without_key(resp, expected):
    """실제로 관찰된 오류 형식 3가지(XML 인증/XML 한도/HTTP 400 JSON)."""
    with pytest.raises(DurError, match=expected) as e:
        make(FakeDur(error=resp))[0].check_interaction("심바스타틴", "클래리트로마이신")
    assert KEY_DECODED not in str(e.value) and KEY_ENCODED not in str(e.value)


def test_http_failure_is_reported_without_key():
    def boom(req):
        raise httpx.ConnectError(f"failed {req.url}")
    c = DurClient(KEY_ENCODED, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(DurError, match="연결") as e:
        c.check_interaction("심바스타틴", "클래리트로마이신")
    assert "abc" not in str(e.value)


def test_short_name_rejected():
    with pytest.raises(DurError):
        make()[0].check_interaction("a", "심바스타틴")


# ---------- 캐시 ----------
def test_cache_persists_across_instances(tmp_path):
    path = str(tmp_path / "dur.db")
    make(cache_path=path)[0].check_interaction("이트라코나졸", "심바스타틴")
    c2, api2 = make(cache_path=path)
    assert c2.check_interaction("이트라코나졸", "심바스타틴")["status"] == "contraindicated"
    assert api2.calls == []          # 새 프로세스에서도 API를 다시 호출하지 않는다


def test_cache_expires_after_ttl(tmp_path):
    now = [1000.0]
    c, api = make(cache_path=str(tmp_path / "d.db"), clock=lambda: now[0])
    c.check_interaction("이트라코나졸", "심바스타틴")
    n = len(api.calls)
    now[0] += 31 * 86400
    c.check_interaction("이트라코나졸", "심바스타틴")
    assert len(api.calls) > n


# ---------- 단일 약물 안전 정보 ----------
def test_drug_safety_includes_age_dose_and_grade_details():
    r = make()[0].drug_safety("졸피뎀")
    assert r["ingredient"] == "졸피뎀타르타르산염"
    assert r["categories"]["특정연령대금기"]["age_base"] == ["18세 이하"]        # 성분서비스에는 연령 기준이 있다
    assert r["categories"]["용량주의"]["max_qty"] == ["10밀리그램"] and r["categories"]["투여기간주의"]["max_term"] == ["4주"]
    assert r["categories"]["임부금기"]["grade"] == ["3등급"]
    assert "노인주의" in r["not_flagged"] and r["refs"][0] == "DUR:임부금기:졸피뎀타르타르산염"


def test_drug_safety_excludes_deleted_and_lists_contraindicated_partners():
    r = make()[0].drug_safety("아스피린")
    assert "임부금기" in r["categories"] and "삭제" not in str(r["categories"])
    assert r["contraindicated_partners"]["names"] == ["메토트렉세이트"]
    assert make()[0].drug_safety("삭제된약")["categories"] == {}        # 삭제된 고시만 있는 약은 '없음'


def test_drug_safety_via_brand_name():
    r = make()[0].drug_safety("타이레놀")   # 아세트아미노펜은 어느 범주에도 없음 → 빈 결과 + 안전 보증 아님 고지
    assert r["categories"] == {} and "안전을 보증하지 않습니다" in r["notice"]


# ---------- 매칭 규칙 ----------
@pytest.mark.parametrize("q,names,expected", [
    ("클래리트로마이신", ("클래리트로마이신제피과립(42%)",), True),
    ("clarithromycin", ("", "Clarithromycin"), True),
    ("질산염", ("희석니트로글리세린", "Dilute Nitroglycerin"), False),
    ("아", ("아스피린",), False),
])
def test_name_match(q, names, expected):
    assert name_match(q, *names) is expected


# ---------- MCP 서버 ----------
def test_server_tools_and_error_mapping(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError
    monkeypatch.setattr(server, "_client", make()[0])
    assert server.check_drug_interaction("심바스타틴", "이트라코나졸")["status"] == "contraindicated"
    assert server.get_drug_safety_info("아스피린")["ingredient"] == "아스피린"
    with pytest.raises(ToolError):
        server.check_drug_interaction("a", "b")


def test_server_registers_both_tools():
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in (tools.tools if hasattr(tools, "tools") else tools)} == {"check_drug_interaction", "get_drug_safety_info"}
