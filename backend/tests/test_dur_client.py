"""식약처 DUR 클라이언트: 실제 API의 특성(품목 쌍 데이터, 500행 초과 시 조용히 0건, XML 오류)을 흉내 낸 가짜 서버로 검증."""
import httpx
import pytest

from mcp_servers.mfds_dur import server
from mcp_servers.mfds_dur.client import NOTICE, DurClient, DurError, name_match

KEY_ENCODED = "abc%2Bdef%2F123%3D%3D"
KEY_DECODED = "abc+def/123=="


def _row(seq, name, ingr, eng, partner, partner_eng, reason, date="20090303"):
    return {"ITEM_SEQ": seq, "ITEM_NAME": name, "INGR_KOR_NAME": ingr, "INGR_ENG_NAME": eng, "MIX": "단일",
            "MIXTURE_INGR_KOR_NAME": partner, "MIXTURE_INGR_ENG_NAME": partner_eng, "PROHBT_CONTENT": reason, "NOTIFICATION_DATE": date}


def build_pairs():
    """품목 쌍 데이터: 제품이 여러 개라 같은 성분 쌍이 반복된다 (실제와 같은 형태)."""
    rows = []
    simva = ("1", "심바스타정20밀리그램(심바스타틴)", "심바스타틴", "Simvastatin")
    for i in range(400):  # 상대 성분 3종 × 제품 400개 = 1200행 → 3페이지
        rows.append(_row(*simva, "클래리트로마이신", "Clarithromycin", "근병증, 횡문근융해의 위험증가"))
        rows.append(_row(*simva, "이트라코나졸", "Itraconazole", "횡문근융해증"))
        rows.append(_row(*simva, "클래리스로마이신", "Clarithromycin", "근병증, 횡문근융해의 위험증가"))
    itra = ("2", "코니트라캡슐(이트라코나졸)", "이트라코나졸", "Itraconazole")
    rows += [_row(*itra, "심바스타틴", "Simvastatin", "횡문근융해증") for _ in range(30)]
    silde = ("3", "부광실데나필정(실데나필)", "실데나필", "Sildenafil")
    rows += [_row(*silde, "희석니트로글리세린", "Dilute Nitroglycerin", "저혈압"), _row(*silde, "니코란딜", "Nicorandil", "저혈압")]
    aspirin = ("4", "이텍스아스피린장용정(아스피린)", "아스피린", "Aspirin")
    rows += [_row(*aspirin, "메토트렉세이트", "Methotrexate", "독성 증가")]
    return rows


CATEGORY_ROWS = {
    "getPwnmTabooInfoList03": [{"ITEM_SEQ": "4", "ITEM_NAME": "이텍스아스피린장용정(아스피린)", "INGR_NAME": "아스피린", "INGR_ENG_NAME": "Aspirin",
                                "MIX_TYPE": "단일", "PROHBT_CONTENT": "임신 3기 동맥관 조기 폐쇄 가능", "REMARK": "경구"}],
    "getCpctyAtentInfoList03": [{"ITEM_SEQ": "9", "ITEM_NAME": "졸피뎀정(졸피뎀)", "INGR_NAME": "졸피뎀", "INGR_ENG_NAME": "Zolpidem",
                                 "MIX_TYPE": "단일", "PROHBT_CONTENT": None, "REMARK": None}],
}


class FakeDur:
    def __init__(self, page_drop=False, error_xml=None):
        self.pairs, self.calls, self.page_drop, self.error_xml = build_pairs(), [], page_drop, error_xml

    def __call__(self, req: httpx.Request) -> httpx.Response:
        p, op = dict(req.url.params), req.url.path.rsplit("/", 1)[-1]
        self.calls.append((op, p))
        if self.error_xml:
            return httpx.Response(200, text=self.error_xml)
        rows = self.pairs if op == "getUsjntTabooInfoList03" else CATEGORY_ROWS.get(op, [])
        if "itemName" in p:
            rows = [r for r in rows if p["itemName"] in r["ITEM_NAME"]]
        if "itemSeq" in p:
            rows = [r for r in rows if r["ITEM_SEQ"] == p["itemSeq"]]
        n, page = int(p["numOfRows"]), int(p["pageNo"])
        if n > 500:  # 실제 API의 특성: 오류 없이 0건
            return httpx.Response(200, json={"header": {"resultCode": "00"}, "body": {"pageNo": page, "totalCount": 0, "numOfRows": n}})
        chunk = rows[(page - 1) * n: page * n]
        if self.page_drop and page == 2:
            chunk = chunk[:10]
        body = {"pageNo": page, "totalCount": len(rows), "numOfRows": n}
        if chunk:
            body["items"] = chunk
        return httpx.Response(200, json={"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": body})


def make(api=None, key=KEY_ENCODED, cache_path=None):
    api = api or FakeDur()
    return DurClient(key, http=httpx.Client(transport=httpx.MockTransport(api)), cache_path=cache_path), api


# ---------- 키/요청 ----------
def test_encoded_key_is_decoded_once():
    c, api = make()
    c.resolve("심바스타틴")
    assert api.calls[0][1]["serviceKey"] == KEY_DECODED  # httpx가 다시 한 번만 인코딩하도록 디코딩해서 전달


def test_missing_key_is_reported():
    with pytest.raises(DurError, match="DATA_GO_KR_API_KEY"):
        DurClient(None)


def test_page_size_never_exceeds_limit():
    c, api = make()
    c.check_interaction("심바스타틴", "클래리트로마이신")
    assert all(int(p["numOfRows"]) <= 500 for _, p in api.calls)


# ---------- 해석 ----------
def test_resolve_prefers_single_ingredient_item_and_reports_rows():
    c, _ = make()
    r = c.resolve("심바스타틴")
    assert r["item_seq"] == "1" and r["ingredient"] == "심바스타틴" and r["rows"] == 1200
    assert c.resolve("존재하지않는약") is None


def test_short_name_rejected():
    with pytest.raises(DurError):
        make()[0].resolve("a")


# ---------- 병용금기 ----------
def test_contraindicated_found_with_reason():
    c, _ = make()
    r = c.check_interaction("심바스타틴", "클래리트로마이신")
    assert r["status"] == "contraindicated" and r["notice"] == NOTICE
    reasons = {x["reason"] for x in r["contraindications"]}
    assert reasons == {"근병증, 횡문근융해의 위험증가"} and r["refs"][0].startswith("DUR:병용금기:")


def test_pairs_are_deduplicated_across_products_and_pages():
    c, api = make()
    r = c.check_interaction("심바스타틴", "클래리트로마이신")   # 클래리트로마이신 품목이 없어 심바스타틴 쪽(1200행)을 펼쳐야 함
    assert r["status"] == "contraindicated" and len(r["contraindications"]) == 1  # 제품 400개 분량의 행이 성분 쌍 1개로
    assert sum(1 for op, p in api.calls if p.get("itemSeq") == "1" and int(p["numOfRows"]) == 500) == 3  # 1200행 = 3페이지


def test_english_partner_name_matches():
    c, _ = make()
    assert c.check_interaction("심바스타틴", "clarithromycin")["status"] == "contraindicated"


def test_reverse_direction_and_smaller_side_first():
    c, api = make()
    r = c.check_interaction("이트라코나졸", "심바스타틴")   # 이트라코나졸 쪽 행이 적다(30 vs 1200)
    assert r["status"] == "contraindicated" and r["checked_from"] == "이트라코나졸"
    assert not any(p.get("itemSeq") == "1" and int(p["numOfRows"]) == 500 for _, p in api.calls)  # 큰 쪽은 펼치지 않음


def test_not_listed_never_claims_safe_and_lists_partners():
    c, _ = make()
    r = c.check_interaction("아스피린", "와파린")
    assert r["status"] == "not_listed" and r["contraindications"] == [] and r["notice"] == NOTICE
    assert "안전하다는 뜻이 아닙니다" in r["hint"] and r["listed_partners"]["names"] == ["메토트렉세이트"]
    assert r["unresolved"] == ["와파린"]


def test_class_name_is_recoverable_via_partner_list():
    """'질산염'은 DUR에 없는 이름이지만, 상대 목록에 니트로글리세린이 있어 LLM이 계열로 이어갈 수 있다."""
    r = make()[0].check_interaction("실데나필", "질산염")
    assert r["status"] == "not_listed" and "희석니트로글리세린" in r["listed_partners"]["names"]
    assert r["listed_partners"]["of"] == "실데나필"


def test_spelling_variant_is_matched_not_missed():
    """실제 사고 재현: LLM이 '클라리스로마이신'으로 호출 → DUR 표기는 '클래리스로마이신'. 미탐하면 금기를 '금기 아님'으로 안내하게 된다."""
    r = make()[0].check_interaction("심바스타틴", "클라리스로마이신")
    assert r["status"] == "contraindicated" and r["match_type"] == "similar_spelling"
    assert "표기가 비슷한" in r["match_note"] and "클래리스로마이신" in r["match_note"]


def test_exact_match_is_labeled_exact():
    assert make()[0].check_interaction("심바스타틴", "이트라코나졸")["match_type"] == "exact"


def test_different_drugs_are_not_fuzzy_matched():
    """과경고를 막기 위한 임계값: 이름이 비슷해 보여도 다른 약(케토코나졸 vs 이트라코나졸)은 매칭하지 않는다."""
    r = make()[0].check_interaction("심바스타틴", "케토코나졸")
    assert r["status"] == "not_listed" and "match_type" not in r
    assert "병용금기로 고시된 성분 전체" in r["listed_partners"]["meaning"]


def test_short_names_never_fuzzy_match():
    from mcp_servers.mfds_dur.client import similar_partners
    assert similar_partners("이소", [{"partner": "이소프로필"}]) == []


def test_both_unresolved():
    r = make()[0].check_interaction("가짜약A", "가짜약B")
    assert r["status"] == "unresolved" and r["notice"] == NOTICE


def test_second_side_is_checked_when_first_misses():
    """작은 쪽 목록에 상대가 없으면 반대편도 확인해 표기 차이로 인한 누락을 줄인다."""
    c, api = make()
    r = c.check_interaction("클래리스로마이신", "심바스타틴")   # 첫 해석은 실패해도 상대 쪽(심바스타틴) 목록에서 찾을 수 있어야 함
    assert r["status"] == "contraindicated"


# ---------- 안정성 ----------
def test_truncated_pages_are_rejected_not_silently_accepted():
    c, _ = make(FakeDur(page_drop=True))
    with pytest.raises(DurError, match="불완전"):
        c.check_interaction("심바스타틴", "클래리트로마이신")


@pytest.mark.parametrize("xml,expected", [
    ("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE KEY IS NOT REGISTERED ERROR.</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>", "등록되지 않았"),
    ("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>", "한도"),
])
def test_xml_errors_become_readable_messages_without_key(xml, expected):
    c, _ = make(FakeDur(error_xml=xml))
    with pytest.raises(DurError, match=expected) as e:
        c.resolve("심바스타틴")
    assert KEY_DECODED not in str(e.value) and KEY_ENCODED not in str(e.value)


def test_http_failure_is_reported_without_key():
    def boom(req):
        raise httpx.ConnectError(f"failed {req.url}")
    c = DurClient(KEY_ENCODED, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(DurError, match="연결") as e:
        c.resolve("심바스타틴")
    assert "abc" not in str(e.value)


# ---------- 캐시 ----------
def test_results_are_cached_in_memory():
    c, api = make()
    big = lambda: sum(1 for _, p in api.calls if int(p["numOfRows"]) == 500)   # 품목 행 전체를 받는 호출
    c.check_interaction("심바스타틴", "클래리트로마이신")
    assert big() == 3
    c.check_interaction("심바스타틴", "클래리트로마이신")   # 완전히 같은 질의 → 추가 호출 없음
    n = len(api.calls)
    c.check_interaction("심바스타틴", "클래리스로마이신")   # 같은 대표 품목, 다른 상대 → 1200행을 다시 받지 않는다
    assert big() == 3 and len(api.calls) - n <= 1


def test_cache_persists_across_instances(tmp_path):
    path = str(tmp_path / "dur.db")
    c1, _ = make(cache_path=path)
    c1.check_interaction("이트라코나졸", "심바스타틴")
    c2, api2 = make(cache_path=path)
    assert c2.check_interaction("이트라코나졸", "심바스타틴")["status"] == "contraindicated"
    assert api2.calls == []          # 새 프로세스에서도 API를 다시 호출하지 않는다


def test_cache_expires_after_ttl(tmp_path):
    now = [1000.0]
    api = FakeDur()
    c = DurClient(KEY_ENCODED, http=httpx.Client(transport=httpx.MockTransport(api)), cache_path=str(tmp_path / "d.db"), clock=lambda: now[0])
    c.resolve("심바스타틴")
    n = len(api.calls)
    now[0] += 31 * 86400
    c.resolve("심바스타틴")
    assert len(api.calls) > n


# ---------- 단일 약물 안전 정보 ----------
def test_drug_safety_categories():
    r = make()[0].drug_safety("아스피린")
    assert r["ingredient"] == "아스피린" and "임부금기" in r["categories"] and "동맥관" in r["categories"]["임부금기"]["notes"][0]
    assert "노인주의" not in r["categories"] and "안전을 보증하지 않습니다" in r["notice"]
    assert r["refs"] == ["DUR:임부금기:아스피린"]


def test_drug_safety_flag_only_category_has_no_notes():
    r = make()[0].drug_safety("졸피뎀")
    assert r["categories"]["용량주의"]["notes"] == []


def test_drug_safety_lists_unflagged_categories_and_age_limitation():
    r = make()[0].drug_safety("아스피린")
    assert "노인주의" in r["not_flagged"] and "임부금기" not in r["not_flagged"]     # '노인주의 없음'을 LLM이 추측하지 않게 명시
    fake_age = {"getSpcifyAgrdeTabooInfoList03": [{"ITEM_SEQ": "9", "ITEM_NAME": "졸피뎀정(졸피뎀)", "INGR_NAME": "졸피뎀", "INGR_ENG_NAME": "Zolpidem",
                                                    "MIX_TYPE": "단일", "PROHBT_CONTENT": "- 안전성 및 유효성 미확립", "REMARK": None}]}
    import tests.test_dur_client as me
    old = dict(me.CATEGORY_ROWS)
    me.CATEGORY_ROWS.update(fake_age)
    try:
        z = make()[0].drug_safety("졸피뎀")
    finally:
        me.CATEGORY_ROWS.clear(); me.CATEGORY_ROWS.update(old)
    assert "API에 포함되어 있지 않습니다" in z["categories"]["특정연령대금기"]["age_note"]   # 연령대를 임의로 노인/소아로 해석하지 못하게


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
