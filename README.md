# MediRail

근거 기반(인용 필수) 의료 AI 에이전트 포트폴리오. 진단·처방은 하지 않으며 최종 판단은 의료진에게 위임.

- backend: FastAPI (Python), 에이전트 루프, RBAC, 가드레일
- mcp_servers: pubmed / mfds_drug / patient_db
- skills: soap-note, drug-interaction-check, emergency-triage, eval-report
- frontend: React (docs/design.md 스타일)
- eval: 45문항 평가, `eval/report.md`
- LLM: OpenRouter (모델 비교)
