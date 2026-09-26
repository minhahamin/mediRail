"""합성 데이터 시드. 모든 인물·기록은 가상이며 실제 환자 정보가 아니다."""
import hashlib
import os
import sqlite3
from datetime import date, datetime, timedelta

DEMO_PASSWORD = "demo1234"


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(8)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 60_000).hex()


def verify_password(pw: str, stored: str) -> bool:
    salt_hex, _ = stored.split("$", 1)
    return hash_password(pw, bytes.fromhex(salt_hex)) == stored


PATIENTS = [  # id, name, birth_year, sex, allergies, medications
    (1, "김하늘", 1978, "F", "페니실린", "암로디핀 5mg"),
    (2, "이도윤", 1992, "M", "", ""),
    (3, "박서연", 1965, "F", "", "메트포르민 500mg"),
    (4, "최민준", 2001, "M", "땅콩", ""),
    (5, "정유나", 1988, "F", "", ""),
    (6, "한지호", 1954, "M", "", "와파린 3mg, 아토르바스타틴 20mg"),
    (7, "오세린", 2015, "F", "", ""),
    (8, "윤태오", 1983, "M", "설파제", ""),
]
USERS = [  # username, role, name, patient_id
    ("patient1", "patient", "김하늘", 1), ("patient2", "patient", "이도윤", 2),
    ("patient3", "patient", "박서연", 3), ("patient4", "patient", "최민준", 4),
    ("doctor1", "doctor", "강서준 (의사)", None), ("doctor2", "doctor", "문지안 (의사)", None),
    ("nurse1", "nurse", "송하린 (간호사)", None), ("admin1", "admin", "임도현 (원무)", None),
]
INTAKES = [
    (1, "3일 전부터 목이 아프고 열이 38.2도까지 올랐다. 기침은 거의 없고 침 삼키기 힘들다. 고혈압약(암로디핀) 복용 중이고 페니실린 알레르기가 있다."),
    (3, "2형 당뇨로 메트포르민 500mg 하루 2회 복용 중. 최근 2주간 갈증과 잦은 소변이 심해짐. 공복혈당 자가측정 180 안팎. 발 저림 있음."),
    (6, "지난 한 주 동안 잇몸에서 피가 나고 멍이 잘 든다. 와파린을 복용 중이며 어제부터 감기약(이부프로펜)을 먹었다."),
]
ENCOUNTERS = [  # patient_id, doctor_username, days_ago, cc, notes
    (2, "doctor1", 2, "기침 5일", "열 37.9, 인후 발적, 폐음 깨끗, SpO2 98%. 의사 메모: 급성 상기도감염 의심, 충분한 수분/휴식, 3일 후 재방문, 악화 시 내원."),
    (3, "doctor2", 5, "당뇨 정기 f/u", "HbA1c 7.8%, BMI 27, 발 검사 이상 없음. 의사 메모: 혈당 조절 미흡, 식이·운동 교육, 다음 방문 시 안과 검진 의뢰 논의."),
    (5, "doctor1", 1, "두통, 어지럼", "혈압 152/96 (2회 측정 평균), 맥박 78. 의사 메모: 고혈압 의심, 가정혈압 2주 기록, 저염식, 2주 후 재방문."),
]


def seed(conn: sqlite3.Connection, today: date | None = None) -> None:
    today = today or date.today()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn.executemany("INSERT INTO patients VALUES (?,?,?,?,?,?)", PATIENTS)
    for i, (u, role, name, pid) in enumerate(USERS, start=1):
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (i, u, hash_password(DEMO_PASSWORD), role, name, pid))
    uid = {u: i for i, (u, *_r) in enumerate(USERS, start=1)}
    conn.executemany("INSERT INTO intakes (patient_id, text, created_at) VALUES (?,?,?)", [(p, t, now) for p, t in INTAKES])
    for pid, doc, ago, cc, notes in ENCOUNTERS:
        conn.execute("INSERT INTO encounters (patient_id, doctor_id, visit_date, chief_complaint, notes) VALUES (?,?,?,?,?)",
                     (pid, uid[doc], (today - timedelta(days=ago)).isoformat(), cc, notes))
    nxt = today + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    for pid, doc, hh, reason in [(1, "doctor1", "10:00", "인후통 재진"), (3, "doctor2", "11:00", "당뇨 상담"), (6, "doctor1", "14:00", "출혈 경향 상담")]:
        conn.execute("INSERT INTO appointments (patient_id, doctor_id, slot, reason, created_at) VALUES (?,?,?,?,?)",
                     (pid, uid[doc], f"{nxt.isoformat()} {hh}", reason, now))
    conn.commit()
