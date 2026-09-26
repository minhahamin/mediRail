"""Agent Skills(SKILL.md) 로더.

절차 지식(SOAP 작성법, 약물 조회 절차 등)을 프롬프트 상수가 아니라 skills/<name>/SKILL.md 파일로 관리한다.
같은 파일을 Claude Code(.claude/skills/)에서도 그대로 쓸 수 있는 표준 형식이며, 백엔드는 사용자 역할에 맞는 스킬만 시스템 프롬프트에 넣는다.

SKILL.md 형식:
    ---
    name: <디렉터리 이름과 동일>
    description: <무엇을 하는 스킬인지, 언제 쓰는지>
    roles: [doctor, nurse]        # 이 스킬을 받는 역할
    tools: [tool_a, tool_b]       # 이 스킬이 쓰는 도구 (등록된 도구와 일치해야 함 - 테스트가 검증)
    ---
    본문(Markdown)
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import ROOT

SKILLS_DIR = ROOT / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    roles: tuple[str, ...]
    tools: tuple[str, ...]
    body: str
    path: Path


class SkillError(Exception):
    pass


def _list(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.strip().strip("[]").split(",") if x.strip())


def parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise SkillError(f"{path}: frontmatter(---)가 없습니다")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "#")):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    for required in ("name", "description"):
        if not meta.get(required):
            raise SkillError(f"{path}: '{required}'가 없습니다")
    return Skill(meta["name"], meta["description"], _list(meta.get("roles", "")), _list(meta.get("tools", "")), m.group(2).strip(), path)


@lru_cache(maxsize=1)
def load_skills(directory: str | None = None) -> dict[str, Skill]:
    root = Path(directory) if directory else SKILLS_DIR
    skills = {}
    for f in sorted(root.glob("*/SKILL.md")):
        s = parse_skill(f)
        skills[s.name] = s
    return skills


def skills_for(role: str) -> list[Skill]:
    return [s for s in load_skills().values() if role in s.roles]


def render(role: str) -> str:
    """역할에 맞는 스킬을 시스템 프롬프트용 텍스트로 만든다. 해당 스킬이 없으면 빈 문자열."""
    skills = skills_for(role)
    if not skills:
        return ""
    blocks = [f"## 스킬: {s.name}\n({s.description})\n\n{s.body}" for s in skills]
    return "# 절차 지식 (Skills)\n아래 절차와 규칙을 따릅니다.\n\n" + "\n\n".join(blocks)
