#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Synthea(의료) 데이터베이스용 역할 기반 접근 제어(RBAC) 권한 정의 생성기.
financial 팀의 permissions.json 포맷을 그대로 따르되, 의료 도메인 13개 역할 ×
18개 테이블에 대해 테이블별/컬럼별 접근 권한과 행 수준 필터를 생성한다.

컬럼 목록은 synthea_1k_csv(실데이터) 헤더 기준.
"""
import json

# ─────────────────────────────────────────────────────────────────────────────
# 1. 테이블별 실제 컬럼 (synthea_1k_csv 헤더 기준)
# ─────────────────────────────────────────────────────────────────────────────
TABLES = {
    "patients": ["Id", "BIRTHDATE", "DEATHDATE", "SSN", "DRIVERS", "PASSPORT",
                 "PREFIX", "FIRST", "LAST", "SUFFIX", "MAIDEN", "MARITAL",
                 "RACE", "ETHNICITY", "GENDER", "BIRTHPLACE", "ADDRESS", "CITY",
                 "STATE", "COUNTY", "ZIP", "LAT", "LON",
                 "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE"],
    "providers": ["Id", "ORGANIZATION", "NAME", "GENDER", "SPECIALITY",
                  "ADDRESS", "CITY", "STATE", "ZIP", "LAT", "LON", "UTILIZATION"],
    "organizations": ["Id", "NAME", "ADDRESS", "CITY", "STATE", "ZIP", "LAT",
                       "LON", "PHONE", "REVENUE", "UTILIZATION"],
    "payers": ["Id", "NAME", "ADDRESS", "CITY", "STATE_HEADQUARTERED", "ZIP",
               "PHONE", "AMOUNT_COVERED", "AMOUNT_UNCOVERED", "REVENUE",
               "COVERED_ENCOUNTERS", "UNCOVERED_ENCOUNTERS", "COVERED_MEDICATIONS",
               "UNCOVERED_MEDICATIONS", "COVERED_PROCEDURES", "UNCOVERED_PROCEDURES",
               "COVERED_IMMUNIZATIONS", "UNCOVERED_IMMUNIZATIONS", "UNIQUE_CUSTOMERS",
               "QOLS_AVG", "MEMBER_MONTHS"],
    "encounters": ["Id", "START", "STOP", "PATIENT", "ORGANIZATION", "PROVIDER",
                   "PAYER", "ENCOUNTERCLASS", "CODE", "DESCRIPTION",
                   "BASE_ENCOUNTER_COST", "TOTAL_CLAIM_COST", "PAYER_COVERAGE",
                   "REASONCODE", "REASONDESCRIPTION"],
    "conditions": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"],
    "medications": ["START", "STOP", "PATIENT", "PAYER", "ENCOUNTER", "CODE",
                    "DESCRIPTION", "BASE_COST", "PAYER_COVERAGE", "DISPENSES",
                    "TOTALCOST", "REASONCODE", "REASONDESCRIPTION"],
    "procedures": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION",
                   "BASE_COST", "REASONCODE", "REASONDESCRIPTION"],
    "observations": ["DATE", "PATIENT", "ENCOUNTER", "CATEGORY", "CODE",
                     "DESCRIPTION", "VALUE", "UNITS", "TYPE"],
    "allergies": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "SYSTEM",
                  "DESCRIPTION", "TYPE", "CATEGORY", "REACTION1", "DESCRIPTION1",
                  "SEVERITY1", "REACTION2", "DESCRIPTION2", "SEVERITY2"],
    "immunizations": ["DATE", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION",
                      "BASE_COST"],
    "careplans": ["Id", "START", "STOP", "PATIENT", "ENCOUNTER", "CODE",
                  "DESCRIPTION", "REASONCODE", "REASONDESCRIPTION"],
    "devices": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "UDI"],
    "supplies": ["DATE", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "QUANTITY"],
    "imaging_studies": ["Id", "DATE", "PATIENT", "ENCOUNTER", "SERIES_UID",
                        "BODYSITE_CODE", "BODYSITE_DESCRIPTION", "MODALITY_CODE",
                        "MODALITY_DESCRIPTION", "INSTANCE_UID", "SOP_CODE",
                        "SOP_DESCRIPTION", "PROCEDURE_CODE"],
    "claims": ["Id", "PATIENTID", "PROVIDERID", "PRIMARYPATIENTINSURANCEID",
               "SECONDARYPATIENTINSURANCEID", "DEPARTMENTID", "PATIENTDEPARTMENTID",
               "DIAGNOSIS1", "DIAGNOSIS2", "DIAGNOSIS3", "DIAGNOSIS4", "DIAGNOSIS5",
               "DIAGNOSIS6", "DIAGNOSIS7", "DIAGNOSIS8", "REFERRINGPROVIDERID",
               "APPOINTMENTID", "CURRENTILLNESSDATE", "SERVICEDATE",
               "SUPERVISINGPROVIDERID", "STATUS1", "STATUS2", "STATUSP",
               "OUTSTANDING1", "OUTSTANDING2", "OUTSTANDINGP", "LASTBILLEDDATE1",
               "LASTBILLEDDATE2", "LASTBILLEDDATEP", "HEALTHCARECLAIMTYPEID1",
               "HEALTHCARECLAIMTYPEID2"],
    "claims_transactions": ["ID", "CLAIMID", "CHARGEID", "PATIENTID", "TYPE",
                            "AMOUNT", "METHOD", "FROMDATE", "TODATE", "PLACEOFSERVICE",
                            "PROCEDURECODE", "MODIFIER1", "MODIFIER2", "DIAGNOSISREF1",
                            "DIAGNOSISREF2", "DIAGNOSISREF3", "DIAGNOSISREF4", "UNITS",
                            "DEPARTMENTID", "NOTES", "UNITAMOUNT", "TRANSFEROUTID",
                            "TRANSFERTYPE", "PAYMENTS", "ADJUSTMENTS", "TRANSFERS",
                            "OUTSTANDING", "APPOINTMENTID", "LINENOTE",
                            "PATIENTINSURANCEID", "FEESCHEDULEID", "PROVIDERID",
                            "SUPERVISINGPROVIDERID"],
    "payer_transitions": ["PATIENT", "MEMBERID", "START_YEAR", "END_YEAR", "PAYER",
                          "SECONDARY_PAYER", "OWNERSHIP", "OWNERNAME"],
}

# 테이블 그룹
CLINICAL = ["conditions", "medications", "procedures", "observations", "allergies",
            "immunizations", "careplans", "devices", "supplies", "imaging_studies"]
MASTER = ["providers", "organizations", "payers"]
BILLING = ["claims", "claims_transactions", "payer_transitions"]
TABLE_ORDER = ["patients"] + CLINICAL + ["encounters"] + BILLING + MASTER

# ─────────────────────────────────────────────────────────────────────────────
# 2. 민감 컬럼 분류 (patients 중심)
# ─────────────────────────────────────────────────────────────────────────────
PAT_LEGAL_ID = ["SSN", "DRIVERS", "PASSPORT"]                       # 🔴 법정 식별번호
PAT_NAME     = ["PREFIX", "FIRST", "LAST", "SUFFIX", "MAIDEN"]      # 🟠 이름
PAT_GEO_FINE = ["ADDRESS", "ZIP", "LAT", "LON", "BIRTHPLACE"]       # 🟠 정밀 위치
PAT_QUASI    = ["BIRTHDATE", "DEATHDATE", "CITY", "STATE", "COUNTY",
                "MARITAL", "RACE", "ETHNICITY", "GENDER"]           # 🟡 준식별자
PAT_FINANCE  = ["HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE"]       # 💲 재무
PAT_DIRECT_ID = PAT_LEGAL_ID + PAT_NAME + PAT_GEO_FINE              # 직접 식별자 전체

# 비용 컬럼 (임상/내원 테이블)
COST_COLS = {
    "medications": ["BASE_COST", "PAYER_COVERAGE", "TOTALCOST"],
    "procedures": ["BASE_COST"],
    "immunizations": ["BASE_COST"],
    "encounters": ["BASE_ENCOUNTER_COST", "TOTAL_CLAIM_COST", "PAYER_COVERAGE"],
}
# 연구용 비식별 시 제거할 직접 링크/자유텍스트/UID 컬럼
DEID_DENY = {
    "conditions": ["PATIENT", "ENCOUNTER"],
    "medications": ["PATIENT", "ENCOUNTER"],
    "procedures": ["PATIENT", "ENCOUNTER"],
    "observations": ["PATIENT", "ENCOUNTER"],
    "allergies": ["PATIENT", "ENCOUNTER"],
    "immunizations": ["PATIENT", "ENCOUNTER"],
    "careplans": ["PATIENT", "ENCOUNTER"],
    "devices": ["PATIENT", "ENCOUNTER", "UDI"],
    "supplies": ["PATIENT", "ENCOUNTER"],
    "imaging_studies": ["PATIENT", "ENCOUNTER", "SERIES_UID", "INSTANCE_UID"],
    "encounters": ["PATIENT", "PROVIDER"],
}

# 환자 식별 컬럼명 (행 수준 필터용)
PATIENT_KEY = {}
for t in CLINICAL + ["encounters"]:
    PATIENT_KEY[t] = "PATIENT"
PATIENT_KEY["payer_transitions"] = "PATIENT"
PATIENT_KEY["claims"] = "PATIENTID"
PATIENT_KEY["claims_transactions"] = "PATIENTID"
PATIENT_KEY["patients"] = "Id"

# ─────────────────────────────────────────────────────────────────────────────
# 3. 연산자 / 컬럼 토큰 정의
# ─────────────────────────────────────────────────────────────────────────────
OPS = {
    "ALL": ["SELECT", "INSERT", "UPDATE", "DELETE"],
    "RWU": ["SELECT", "INSERT", "UPDATE"],
    "RU":  ["SELECT", "UPDATE"],
    "RI":  ["SELECT", "INSERT"],
    "R":   ["SELECT"],
    "NONE": [],
}


def resolve_columns(table, token):
    """allowed_columns 토큰 → 실제 컬럼 리스트(테이블 컬럼 순서 유지)."""
    cols = TABLES[table]
    if token == "ALL":
        return list(cols)
    if token == "NONE":
        return []
    if isinstance(token, tuple) and token[0] == "ONLY":
        keep = set(token[1])
        return [c for c in cols if c in keep]
    if isinstance(token, tuple) and token[0] == "EXCEPT":
        drop = set(token[1])
        return [c for c in cols if c not in drop]
    if token == "EXCEPT_COST":
        drop = set(COST_COLS.get(table, []))
        return [c for c in cols if c not in drop]
    if token == "DEID":
        drop = set(DEID_DENY.get(table, []))
        return [c for c in cols if c not in drop]
    raise ValueError(f"Unknown column token: {token}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. 행 수준 필터 생성기
# ─────────────────────────────────────────────────────────────────────────────
def self_filter(table):
    """환자 본인 데이터만: {current_user_patient_id} 치환."""
    key = PATIENT_KEY.get(table)
    if not key:
        return None
    if table == "patients":
        return "Id = '{current_user_patient_id}'"
    return f"{key} = '{{current_user_patient_id}}'"


def physician_filter(table):
    """담당의: 본인이 PROVIDER로 참여한 내원의 환자만."""
    sub = "SELECT PATIENT FROM encounters WHERE PROVIDER = '{current_user_provider_id}'"
    key = PATIENT_KEY.get(table)
    if not key:
        return None
    if table == "patients":
        return f"Id IN ({sub})"
    if table == "encounters":
        return ("PROVIDER = '{current_user_provider_id}' "
                f"OR PATIENT IN ({sub})")
    return f"{key} IN ({sub})"


# ─────────────────────────────────────────────────────────────────────────────
# 5. 역할별 정책 정의
#    rules: table 또는 group 키 → (ops_token, column_token)
#    group 키(CLINICAL/MASTER/BILLING)는 그룹 전체에 적용, 개별 테이블 키가 우선.
#    row_filter_mode: None | "self" | "physician"
# ─────────────────────────────────────────────────────────────────────────────
GROUP_KEYS = {"CLINICAL": CLINICAL, "MASTER": MASTER, "BILLING": BILLING}

# 직군이 보는 환자 기본 인적사항(이름+기본 인구통계, 🔴법정ID/💲재무/정밀위치 제외)
PAT_CLINICAL_VIEW = ("EXCEPT", PAT_LEGAL_ID + PAT_FINANCE + ["LAT", "LON"])
# 간호/약사/기사: 최소 인적사항
PAT_MIN_VIEW = ("ONLY", ["Id", "FIRST", "LAST", "BIRTHDATE", "GENDER", "MARITAL"])
# 보험심사: 직접식별자 차단, 보험·기본 인구통계만
PAT_INS_VIEW = ("ONLY", ["Id", "BIRTHDATE", "GENDER", "STATE", "ZIP",
                         "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE"])
# 연구/분석: 비식별 (직접식별자·Id·날짜형 식별자 제거)
PAT_DEID_VIEW = ("ONLY", ["MARITAL", "RACE", "ETHNICITY", "GENDER", "STATE",
                          "COUNTY", "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE"])
# 감사: 재무 추적용 + 익명 Id
PAT_AUDIT_VIEW = ("ONLY", ["Id", "STATE", "COUNTY",
                           "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE"])
# 환자 본인: 본인 정보 (🔴법정ID·내부좌표는 마스킹)
PAT_SELF_VIEW = ("EXCEPT", PAT_LEGAL_ID + ["LAT", "LON"])

# 마스터 테이블 제한 뷰
ORG_BASIC = ("EXCEPT", ["REVENUE", "UTILIZATION", "LAT", "LON"])
PAYER_BASIC = ("ONLY", ["Id", "NAME", "ADDRESS", "CITY", "STATE_HEADQUARTERED",
                        "ZIP", "PHONE"])
PROV_DEID = ("EXCEPT", ["NAME", "ADDRESS", "LAT", "LON"])

ROLE_SPECS = [
    {
        "role": "system_admin", "level": 1,
        "display_name": "시스템 관리자 (Database Administrator)",
        "description": "데이터베이스 전체에 대한 완전한 접근 권한. 스키마 관리, 정합성 유지, 백업·복구 등 모든 작업 수행. 환자 PII·임상·재무 데이터 전체 CRUD 가능.",
        "row_filter_mode": None,
        "rules": {"patients": ("ALL", "ALL"), "CLINICAL": ("ALL", "ALL"),
                  "encounters": ("ALL", "ALL"), "BILLING": ("ALL", "ALL"),
                  "MASTER": ("ALL", "ALL")},
        "note": "전체 관리 (CRUD)",
    },
    {
        "role": "privacy_officer", "level": 2,
        "display_name": "개인정보보호책임자 / 준법감시인 (Privacy & Compliance Officer)",
        "description": "HIPAA·개인정보 규제 준수와 PHI/PII 접근 감사를 위해 모든 테이블에 대한 읽기 권한 보유. 데이터 수정 권한은 없으며 감사·모니터링 목적으로만 접근.",
        "row_filter_mode": None,
        "rules": {"patients": ("R", "ALL"), "CLINICAL": ("R", "ALL"),
                  "encounters": ("R", "ALL"), "BILLING": ("R", "ALL"),
                  "MASTER": ("R", "ALL")},
        "note": "전체 조회 전용 (감사·규제 감시)",
    },
    {
        "role": "hospital_director", "level": 3,
        "display_name": "병원장 / 의료원장 (Hospital Director)",
        "description": "병원 운영 총괄. 대부분 테이블에 대한 조회·입력·수정 권한 보유. 재무 거래(claims_transactions)는 조회만 가능하며, 환자 법정 식별번호(SSN 등)와 삭제 권한은 없음.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("RWU", ("EXCEPT", PAT_LEGAL_ID)),
            "CLINICAL": ("RWU", "ALL"),
            "encounters": ("RWU", "ALL"),
            "claims": ("RWU", "ALL"),
            "claims_transactions": ("R", "ALL"),     # 재무 거래는 조회만
            "payer_transitions": ("RWU", "ALL"),
            "MASTER": ("RWU", "ALL"),
        },
        "note": "운영 총괄 (재무거래는 조회만, SSN·삭제 제외)",
    },
    {
        "role": "attending_physician", "level": 4,
        "display_name": "주치의 / 임상의사 (Attending Physician)",
        "description": "진료·처방의 주체. 본인이 담당하는 환자(행 수준 필터)의 임상 기록과 내원 기록을 전체 CRUD. 환자 인적사항은 진료에 필요한 컬럼만 조회하며 법정 식별번호·재무 정보는 제외. 청구는 본인 환자 건만 제한적으로 조회.",
        "row_filter_mode": "physician",
        "rules": {
            "patients": ("R", PAT_CLINICAL_VIEW),
            "CLINICAL": ("ALL", "ALL"),
            "encounters": ("ALL", "ALL"),
            "claims": ("R", ("EXCEPT", ["OUTSTANDING1", "OUTSTANDING2", "OUTSTANDINGP"])),
            "claims_transactions": ("R", ("ONLY", ["ID", "CLAIMID", "PATIENTID",
                                                   "TYPE", "PROCEDURECODE", "FROMDATE",
                                                   "TODATE", "DIAGNOSISREF1"])),
            "payer_transitions": ("R", ("ONLY", ["PATIENT", "PAYER", "START_YEAR",
                                                 "END_YEAR"])),
            "MASTER": ("R", "ALL"),
        },
        "note": "담당환자 임상 전체 CRUD (행수준 필터, 청구는 제한 조회)",
    },
    {
        "role": "nurse", "level": 5,
        "display_name": "간호사 (Registered Nurse)",
        "description": "활력징후·투약·예방접종 등 임상 실무 담당. 관찰·접종·물품·의료기기는 입력·수정 가능, 투약 기록은 수정 가능. 진단·처방·시술은 조회만. 청구·재무 데이터는 접근 불가.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("R", PAT_MIN_VIEW),
            "observations": ("RWU", "ALL"),
            "immunizations": ("RWU", "ALL"),
            "supplies": ("RWU", "ALL"),
            "devices": ("RWU", "ALL"),
            "medications": ("RU", "EXCEPT_COST"),       # 투약 기록 수정, 비용 제외
            "allergies": ("RWU", "ALL"),
            "conditions": ("R", "ALL"),
            "procedures": ("R", "EXCEPT_COST"),
            "careplans": ("RWU", "ALL"),
            "imaging_studies": ("R", "ALL"),
            "encounters": ("R", "EXCEPT_COST"),
            "BILLING": ("NONE", "NONE"),
            "MASTER": ("R", ("ONLY", ["Id", "NAME", "SPECIALITY", "ORGANIZATION",
                                      "CITY", "STATE", "PHONE"])),
        },
        "note": "활력·투약·접종 입력/수정, 청구 접근 불가",
    },
    {
        "role": "pharmacist", "level": 6,
        "display_name": "약사 (Pharmacist)",
        "description": "조제·복약지도·약물상호작용 검토 담당. 투약(medications)은 입력·수정 가능. 약물 안전성 검토를 위해 알레르기·진단·관찰은 조회. 그 외 임상은 최소 조회, 청구·재무는 접근 불가.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("R", PAT_MIN_VIEW),
            "medications": ("RWU", "ALL"),
            "allergies": ("R", "ALL"),
            "conditions": ("R", "ALL"),
            "observations": ("R", "ALL"),       # 신장/체중/eGFR 등 용량 계산
            "immunizations": ("RWU", "ALL"),
            "procedures": ("R", "EXCEPT_COST"),
            "careplans": ("R", "ALL"),
            "devices": ("R", "ALL"),
            "supplies": ("R", "ALL"),
            "imaging_studies": ("NONE", "NONE"),
            "encounters": ("R", "EXCEPT_COST"),
            "BILLING": ("NONE", "NONE"),
            "MASTER": ("R", ("ONLY", ["Id", "NAME", "SPECIALITY", "ORGANIZATION"])),
        },
        "note": "투약 조제 입력/수정, 알레르기·진단 조회",
    },
    {
        "role": "clinical_technician", "level": 7,
        "display_name": "임상병리·영상 기사 (Clinical / Imaging Technician)",
        "description": "검사·영상 결과 등록 담당. 관찰(검사결과)·영상검사·의료기기 정보를 입력·수정. 검사 의뢰 확인을 위해 내원·시술은 조회. 진단·처방 변경 권한과 청구 접근은 없음.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("R", PAT_MIN_VIEW),
            "observations": ("RWU", "ALL"),
            "imaging_studies": ("RWU", "ALL"),
            "devices": ("RWU", "ALL"),
            "procedures": ("R", "EXCEPT_COST"),
            "conditions": ("R", "ALL"),
            "allergies": ("R", "ALL"),
            "medications": ("NONE", "NONE"),
            "immunizations": ("R", "ALL"),
            "careplans": ("R", "ALL"),
            "supplies": ("R", "ALL"),
            "encounters": ("R", "EXCEPT_COST"),
            "BILLING": ("NONE", "NONE"),
            "MASTER": ("R", ("ONLY", ["Id", "NAME", "SPECIALITY", "ORGANIZATION"])),
        },
        "note": "검사·영상 결과 입력/수정, 진단 변경·청구 불가",
    },
    {
        "role": "medical_coder", "level": 8,
        "display_name": "의료코딩·청구 담당 (Medical Coder / Biller)",
        "description": "진단·시술 코드를 부여하고 보험 청구를 생성·관리. 청구 테이블은 입력·수정 가능. 임상 기록은 코딩 근거 확인용으로 조회만 가능하며 변경 불가. 환자 PII는 연결 키(Id) 외 접근 불가.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("R", ("ONLY", ["Id"])),     # 연결 키만, PII 차단
            "CLINICAL": ("R", "ALL"),
            "encounters": ("R", "ALL"),
            "claims": ("RWU", "ALL"),
            "claims_transactions": ("RWU", "ALL"),
            "payer_transitions": ("R", "ALL"),
            "MASTER": ("R", "ALL"),
        },
        "note": "청구 생성/수정, 임상은 코딩용 조회, 환자 PII 차단",
    },
    {
        "role": "registration_clerk", "level": 9,
        "display_name": "원무 / 접수 (Registration Clerk)",
        "description": "환자 등록·보험 접수·내원 예약 담당. 환자 인적·주소·연락 정보와 보험 가입 이력을 입력·수정. 임상 상세는 접근 불가. 법정 식별번호(SSN 등)와 재무 정보는 마스킹되어 보이지 않음.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("RWU", ("EXCEPT", PAT_LEGAL_ID + PAT_FINANCE)),
            "encounters": ("RI", ("EXCEPT", ["TOTAL_CLAIM_COST", "PAYER_COVERAGE"])),
            "CLINICAL": ("NONE", "NONE"),
            "claims": ("R", ("ONLY", ["Id", "PATIENTID", "PROVIDERID",
                                      "PRIMARYPATIENTINSURANCEID", "STATUS1",
                                      "SERVICEDATE"])),
            "claims_transactions": ("R", ("ONLY", ["ID", "CLAIMID", "PATIENTID",
                                                   "TYPE", "OUTSTANDING"])),
            "payer_transitions": ("RWU", "ALL"),
            "providers": ("R", ("ONLY", ["Id", "NAME", "SPECIALITY", "ORGANIZATION"])),
            "organizations": ("R", ORG_BASIC),
            "payers": ("R", PAYER_BASIC),
        },
        "note": "환자등록·보험접수 입력/수정, 임상 불가, SSN·재무 마스킹",
    },
    {
        "role": "insurance_examiner", "level": 10,
        "display_name": "보험심사역 (Insurance Claims Examiner)",
        "description": "보험사 측 청구 적정성 심사·지급 담당. 청구·거래·보험 가입 이력을 조회하고 청구 상태를 갱신. 의학적 필요성 확인을 위해 진단 코드만 조회. 환자 직접 식별자(이름·주소·법정ID)는 차단.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("R", PAT_INS_VIEW),
            "conditions": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"])),
            "procedures": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "CODE",
                                          "DESCRIPTION", "BASE_COST"])),
            "medications": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "CODE",
                                           "DESCRIPTION", "TOTALCOST", "PAYER_COVERAGE"])),
            "immunizations": ("R", "ALL"),
            "observations": ("NONE", "NONE"),
            "allergies": ("NONE", "NONE"),
            "careplans": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION"])),
            "devices": ("R", "ALL"),
            "supplies": ("R", "ALL"),
            "imaging_studies": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "MODALITY_CODE",
                                               "MODALITY_DESCRIPTION", "PROCEDURE_CODE"])),
            "encounters": ("R", "ALL"),
            "claims": ("RU", "ALL"),                 # 청구 상태(STATUS) 갱신
            "claims_transactions": ("R", "ALL"),
            "payer_transitions": ("R", "ALL"),
            "MASTER": ("R", "ALL"),
        },
        "note": "청구 심사·상태 갱신, 진단코드만 조회, 직접식별자 차단",
    },
    {
        "role": "research_analyst", "level": 11,
        "display_name": "임상연구 · 데이터 분석가 (Clinical Research Analyst)",
        "description": "코호트·통계·품질지표 분석 담당. 비식별 데이터만 조회 가능(읽기 전용). 직접 식별자와 환자/내원 링크 키, 자유 텍스트, 정밀 위치는 차단. 날짜는 연 단위 일반화, 우편번호는 3자리로 절단된 비식별 뷰를 통해 접근하는 것을 전제로 한다.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("R", PAT_DEID_VIEW),
            "CLINICAL": ("R", "DEID"),
            "encounters": ("R", "DEID"),
            "claims": ("R", ("ONLY", ["DEPARTMENTID", "DIAGNOSIS1", "SERVICEDATE",
                                      "STATUS1", "HEALTHCARECLAIMTYPEID1"])),
            "claims_transactions": ("R", ("ONLY", ["TYPE", "AMOUNT", "PROCEDURECODE",
                                                   "UNITS", "PAYMENTS", "ADJUSTMENTS",
                                                   "OUTSTANDING"])),
            "payer_transitions": ("R", ("ONLY", ["PAYER", "START_YEAR", "END_YEAR",
                                                 "OWNERSHIP"])),
            "providers": ("R", PROV_DEID),
            "organizations": ("R", "ALL"),       # 기관 집계 통계
            "payers": ("R", "ALL"),              # 보험사 집계 통계
        },
        "note": "비식별 집계 조회 전용, 식별자·링크키·자유텍스트 차단",
    },
    {
        "role": "external_auditor", "level": 12,
        "display_name": "외부 회계 감사인 (External Auditor)",
        "description": "청구·수납·매출의 회계 정합성을 감사하는 외부 감사인. 재무·청구 테이블과 기관·보험사 마스터를 전체 조회. 임상 기록은 비용 근거 확인 범위로 조회. 환자 PII는 익명 Id와 지역 정보 외에는 차단되며 모든 변경은 불가.",
        "row_filter_mode": None,
        "rules": {
            "patients": ("R", PAT_AUDIT_VIEW),
            "encounters": ("R", ("ONLY", ["Id", "START", "STOP", "PATIENT",
                                          "ORGANIZATION", "PROVIDER", "PAYER",
                                          "ENCOUNTERCLASS", "CODE",
                                          "BASE_ENCOUNTER_COST", "TOTAL_CLAIM_COST",
                                          "PAYER_COVERAGE"])),
            "medications": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "CODE", "BASE_COST",
                                           "PAYER_COVERAGE", "DISPENSES", "TOTALCOST"])),
            "procedures": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "CODE", "BASE_COST"])),
            "immunizations": ("R", "ALL"),
            "conditions": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "CODE"])),
            "observations": ("NONE", "NONE"),
            "allergies": ("NONE", "NONE"),
            "careplans": ("NONE", "NONE"),
            "devices": ("R", ("ONLY", ["PATIENT", "ENCOUNTER", "CODE", "UDI"])),
            "supplies": ("R", "ALL"),
            "imaging_studies": ("NONE", "NONE"),
            "claims": ("R", "ALL"),
            "claims_transactions": ("R", "ALL"),
            "payer_transitions": ("R", "ALL"),
            "MASTER": ("R", "ALL"),
        },
        "note": "재무·청구 전체 조회, 임상은 비용근거만, PII 차단",
    },
    {
        "role": "patient", "level": 13,
        "display_name": "환자 본인 (Patient / Self-Service)",
        "description": "환자 포털(PHR)을 통해 본인 데이터만 조회하는 일반 환자. 모든 테이블에 행 수준 필터가 적용되어 본인 PATIENT/PATIENTID 행만 접근 가능. 타 환자 데이터와 의료진·기관·보험사 내부 마스터에는 접근 불가하며, 모든 변경은 불가. 법정 식별번호와 내부 좌표는 마스킹.",
        "row_filter_mode": "self",
        "rules": {
            "patients": ("R", PAT_SELF_VIEW),
            "CLINICAL": ("R", "ALL"),
            "encounters": ("R", "ALL"),
            "claims": ("R", ("EXCEPT", ["SUPERVISINGPROVIDERID", "REFERRINGPROVIDERID"])),
            "claims_transactions": ("R", ("EXCEPT", ["NOTES", "LINENOTE", "FEESCHEDULEID",
                                                     "TRANSFEROUTID"])),
            "payer_transitions": ("R", "ALL"),
            "MASTER": ("NONE", "NONE"),
        },
        "note": "본인 데이터만 조회 (행수준 필터), 마스터 접근 불가",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 6. 빌드
# ─────────────────────────────────────────────────────────────────────────────
TABLE_KO = {
    "patients": "환자(개인식별정보 PII)", "providers": "의료진", "organizations": "의료기관",
    "payers": "보험사", "encounters": "내원 기록", "conditions": "진단",
    "medications": "투약/처방", "procedures": "시술", "observations": "관찰/검사결과",
    "allergies": "알레르기", "immunizations": "예방접종", "careplans": "케어플랜",
    "devices": "의료기기", "supplies": "의료용품", "imaging_studies": "영상검사",
    "claims": "보험청구", "claims_transactions": "청구 거래내역",
    "payer_transitions": "보험 가입이력",
}


def expand_rules(spec):
    """그룹 키를 개별 테이블로 펼치고, 개별 테이블 키로 덮어쓴다."""
    resolved = {}
    rules = spec["rules"]
    # 1) 그룹 먼저
    for gkey, tlist in GROUP_KEYS.items():
        if gkey in rules:
            for t in tlist:
                resolved[t] = rules[gkey]
    # 2) 개별 테이블(그룹 덮어쓰기)
    for k, v in rules.items():
        if k in GROUP_KEYS:
            continue
        resolved[k] = v
    return resolved


def build_role(spec):
    resolved = expand_rules(spec)
    table_perms = {}
    for t in TABLE_ORDER:
        ops_tok, col_tok = resolved.get(t, ("NONE", "NONE"))
        ops = OPS[ops_tok]
        allowed = resolve_columns(t, col_tok)
        denied = [c for c in TABLES[t] if c not in allowed]
        # 행 수준 필터: 조회 권한이 있고 모드가 지정된 경우에만
        rf = None
        if ops and spec["row_filter_mode"] == "self":
            rf = self_filter(t)
        elif ops and spec["row_filter_mode"] == "physician":
            rf = physician_filter(t)
        # 접근 불가 테이블 설명
        if not ops:
            desc = f"{TABLE_KO[t]} — 접근 불가 (업무 범위 밖)"
        else:
            desc = f"{TABLE_KO[t]} — {spec['note']}"
        table_perms[t] = {
            "allowed_operations": ops,
            "allowed_columns": allowed,
            "denied_columns": denied,
            "row_filter": rf,
            "description": desc,
        }
    return {
        "role_name": spec["role"],
        "display_name": spec["display_name"],
        "description": spec["description"],
        "level": spec["level"],
        "table_permissions": table_perms,
    }


def main():
    roles = {}
    levels = []
    for spec in ROLE_SPECS:
        roles[spec["role"]] = build_role(spec)
        levels.append({"level": spec["level"], "role": spec["role"],
                       "display_name": spec["display_name"].split(" (")[0]})

    doc = {
        "metadata": {
            "project": "LLM SQL Agent with Role-Based Access Control",
            "database": "synthea (healthcare / EHR)",
            "description": ("Synthea 합성 의료 데이터베이스에 대한 역할 기반 접근 제어(RBAC) "
                            "권한 정의. 각 역할은 테이블별·컬럼별 접근 권한과 행 수준 필터를 가짐. "
                            "HIPAA(PHI), 개인정보(PII), 재무·청구 규제를 반영하여 최소권한·직무분리 "
                            "원칙으로 설계."),
            "tables": TABLE_ORDER,
            "supported_operations": ["SELECT", "INSERT", "UPDATE", "DELETE"],
            "sensitivity_classification": {
                "patients.legal_identifiers": PAT_LEGAL_ID,
                "patients.direct_identifiers": PAT_DIRECT_ID,
                "patients.quasi_identifiers": PAT_QUASI,
                "patients.financial": PAT_FINANCE,
                "row_filter_placeholders": ["{current_user_patient_id}",
                                            "{current_user_provider_id}"],
                "notes": ("research_analyst는 날짜 연단위 일반화·우편번호 3자리 절단 등 "
                          "HIPAA Safe Harbor 비식별 뷰를 통해 접근하는 것을 전제로 함.")
            }
        },
        "role_hierarchy": {
            "description": ("의료기관 조직 구조 기반 역할 계층. level 숫자가 낮을수록 높은 권한. "
                            "각 역할은 독립적으로 정의되며 상위 역할 권한을 자동 상속하지 않음."),
            "levels": levels,
        },
        "roles": roles,
    }

    out = "/home/jskwon/2026S/bkms1/permissions_medical.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"WROTE {out}")
    print(f"roles={len(roles)} tables={len(TABLE_ORDER)} blocks={len(roles)*len(TABLE_ORDER)}")


if __name__ == "__main__":
    main()
