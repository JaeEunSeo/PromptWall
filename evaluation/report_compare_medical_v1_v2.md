# Medical RBAC SQL 생성 평가 리포트 — v1 vs v2

- 채점기: `answer_checker_positional.py` (컬럼 위치 기준 결과 비교)
- 입력: `report_pos_medical_v1.jsonl` (prompt v1) vs `report_pos_medical_v2.jsonl` (prompt v2)
- 총 시나리오: 78개, 역할 13종

## 1. 전체 요약

| 지표 | v1 | v2 | Δ(v2−v1) |
|---|---|---|---|
| 시나리오 수 | 78 | 78 | - |
| **Status 정확도**(ALLOW/DENY 일치) | 64/78 (82.1%) | 69/78 (88.5%) | +5 |
| **Final match**(status+결과 일치) | 47/78 (60.3%) | 47/78 (60.3%) | +0 |
| ALLOW건 결과 일치 | 11/28 | 11/33 | - |

## 2. Confusion Matrix (gold status × pred status)

### v1

gold \ pred | ALLOW | DENY | 합계
---|---|---|---
**ALLOW** | 28 | 14 | 42
**DENY** | 0 | 36 | 36

### v2

gold \ pred | ALLOW | DENY | 합계
---|---|---|---
**ALLOW** | 33 | 9 | 42
**DENY** | 0 | 36 | 36

## 3. 역할별 정답/오답 (final match)

| 역할 | v1 정답 | v1 오답 | v2 정답 | v2 오답 | Δ정답 |
|---|---|---|---|---|---|
| attending_physician | 4 | 2 | 5 | 1 | +1 🔺 |
| clinical_technician | 3 | 3 | 3 | 3 | +0 |
| external_auditor | 3 | 3 | 5 | 1 | +2 🔺 |
| hospital_director | 3 | 3 | 4 | 2 | +1 🔺 |
| insurance_examiner | 3 | 3 | 3 | 3 | +0 |
| medical_coder | 3 | 3 | 3 | 3 | +0 |
| nurse | 3 | 3 | 4 | 2 | +1 🔺 |
| patient | 5 | 1 | 3 | 3 | -2 🔻 |
| pharmacist | 5 | 1 | 3 | 3 | -2 🔻 |
| privacy_officer | 3 | 3 | 4 | 2 | +1 🔺 |
| registration_clerk | 3 | 3 | 3 | 3 | +0 |
| research_analyst | 6 | 0 | 4 | 2 | -2 🔻 |
| system_admin | 3 | 3 | 3 | 3 | +0 |
| **합계** | 47 | 31 | 47 | 31 | +0 |

### 역할별 final match (v2, ▇=정답비율)

```
attending_physician    ▇▇▇▇▇▇▇▇·· 5/6
clinical_technician    ▇▇▇▇▇····· 3/6
external_auditor       ▇▇▇▇▇▇▇▇·· 5/6
hospital_director      ▇▇▇▇▇▇▇··· 4/6
insurance_examiner     ▇▇▇▇▇····· 3/6
medical_coder          ▇▇▇▇▇····· 3/6
nurse                  ▇▇▇▇▇▇▇··· 4/6
patient                ▇▇▇▇▇····· 3/6
pharmacist             ▇▇▇▇▇····· 3/6
privacy_officer        ▇▇▇▇▇▇▇··· 4/6
registration_clerk     ▇▇▇▇▇····· 3/6
research_analyst       ▇▇▇▇▇▇▇··· 4/6
system_admin           ▇▇▇▇▇····· 3/6
```

## 4. 불일치(오답) 사유 분포

| 사유 | v1 | v2 |
|---|---|---|
| status_mismatch (gold=ALLOW pred=DENY) | 14 | 9 |
| missing_rows=1; extra_rows=1 | 4 | 5 |
| column_count_mismatch gold=9 pred=29 (gold_cols=['id', 'patientid', 'providerid', 'status1', 'status2', 'statusp', 'outstanding1', 'outstanding2', 'outstandingp'] pred_cols=['id', 'patientid', 'providerid', 'primarypatientinsuranceid', 'secondarypatientinsuranceid', 'departmentid', 'patientdepartmentid', 'diagnosis1', 'diagnosis2', 'diagnosis3', 'diagnosis4', 'diagnosis5', 'diagnosis6', 'diagnosis7', 'diagnosis8', 'appointmentid', 'currentillnessdate', 'servicedate', 'status1', 'status2', 'statusp', 'outstanding1', 'outstanding2', 'outstandingp', 'lastbilleddate1', 'lastbilleddate2', 'lastbilleddatep', 'healthcareclaimtypeid1', 'healthcareclaimtypeid2']) | 1 | 1 |
| pred_sql_error: ProgrammingError: Incorrect number of bindings supplied. The current statement uses 2, and there are 0 supplied. | 2 | 0 |
| missing_rows=794 | 0 | 2 |
| pred_sql_error: IntegrityError: UNIQUE constraint failed: patients.id | 0 | 2 |
| column_count_mismatch gold=33 pred=29 (gold_cols=['id', 'claimid', 'chargeid', 'patientid', 'type', 'amount', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'modifier1', 'modifier2', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'departmentid', 'notes', 'unitamount', 'transferoutid', 'transfertype', 'payments', 'adjustments', 'transfers', 'outstanding', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid'] pred_cols=['transaction_id', 'claimid', 'chargeid', 'patientid', 'type', 'amount', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'departmentid', 'notes', 'unitamount', 'payments', 'adjustments', 'transfers', 'outstanding', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid']) | 0 | 1 |
| column_count_mismatch gold=33 pred=34 (gold_cols=['id', 'claimid', 'chargeid', 'patientid', 'type', 'amount', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'modifier1', 'modifier2', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'departmentid', 'notes', 'unitamount', 'transferoutid', 'transfertype', 'payments', 'adjustments', 'transfers', 'outstanding', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid'] pred_cols=['id', 'claimid', 'chargeid', 'patientid', 'type', 'amount', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'modifier1', 'modifier2', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'departmentid', 'notes', 'unitamount', 'transferoutid', 'transfertype', 'payments', 'adjustments', 'transfers', 'outstanding', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid', 'payments']) | 1 | 0 |
| column_count_mismatch gold=4 pred=2 (gold_cols=['patient', 'encounter', 'code', 'description'] pred_cols=['code', 'description']) | 0 | 1 |
| missing_rows=38076 | 0 | 1 |
| column_count_mismatch gold=3 pred=2 (gold_cols=['id', 'total_claim_cost', 'payer_coverage'] pred_cols=['total_claim_cost', 'payer_coverage']) | 1 | 0 |
| missing_rows=1163; extra_rows=1; alias_differs: gold=['patientid', 'total_payments', 'total_adjustments', 'total_transfers'] pred=['total_payments', 'total_adjustments', 'total_transfers', 'grand_total'] | 0 | 1 |
| column_count_mismatch gold=25 pred=4 (gold_cols=['id', 'birthdate', 'deathdate', 'ssn', 'drivers', 'passport', 'prefix', 'first', 'last', 'suffix', 'maiden', 'marital', 'race', 'ethnicity', 'gender', 'birthplace', 'address', 'city', 'state', 'county', 'zip', 'lat', 'lon', 'healthcare_expenses', 'healthcare_coverage'] pred_cols=['id', 'ssn', 'drivers', 'passport']) | 1 | 0 |
| column_count_mismatch gold=4 pred=3 (gold_cols=['id', 'name', 'revenue', 'utilization'] pred_cols=['name', 'revenue', 'utilization']) | 1 | 0 |
| column_count_mismatch gold=6 pred=2 (gold_cols=['start', 'stop', 'patient', 'encounter', 'code', 'description'] pred_cols=['code', 'description']) | 1 | 0 |
| missing_rows=2; extra_rows=2; alias_differs: gold=['status1', 'claim_count', 'outstanding_total'] pred=['total_outstanding', 'status1', 'count_per_status'] | 1 | 0 |
| column_count_mismatch gold=2 pred=4 (gold_cols=['code', 'avg_totalcost'] pred_cols=['medication_code', 'medication_description', 'medication_record_count', 'avg_totalcost']) | 0 | 1 |
| missing_rows=39; extra_rows=172; alias_differs: gold=['start', 'stop', 'patient', 'payer', 'encounter', 'code', 'description', 'base_cost', 'payer_coverage', 'dispenses', 'totalcost', 'reasoncode', 'reasondescription'] pred=['record_type', 'record_start', 'record_stop', 'code', 'description', 'payer', 'dispenses', 'totalcost', 'reasoncode', 'reasondescription', 'encounter_id', 'encounter_start', 'encounter_stop'] | 0 | 1 |
| column_count_mismatch gold=33 pred=30 (gold_cols=['id', 'claimid', 'chargeid', 'patientid', 'type', 'amount', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'modifier1', 'modifier2', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'departmentid', 'notes', 'unitamount', 'transferoutid', 'transfertype', 'payments', 'adjustments', 'transfers', 'outstanding', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid'] pred_cols=['transaction_id', 'claimid', 'chargeid', 'transaction_type', 'line_amount', 'payments', 'adjustments', 'transfers', 'outstanding', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'modifier1', 'modifier2', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'unitamount', 'departmentid', 'notes', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid']) | 0 | 1 |
| pred_sql_error: OperationalError: unrecognized token: "{" | 1 | 0 |
| pred_sql_error: ProgrammingError: Incorrect number of bindings supplied. The current statement uses 8, and there are 0 supplied. | 1 | 0 |
| column_count_mismatch gold=4 pred=3 (gold_cols=['patientid', 'total_payments', 'total_adjustments', 'total_transfers'] pred_cols=['Total_Payments', 'Total_Adjustments', 'Total_Transfers']) | 1 | 0 |
| column_count_mismatch gold=9 pred=8 (gold_cols=['date', 'patient', 'encounter', 'category', 'code', 'description', 'value', 'units', 'type'] pred_cols=['date', 'encounter', 'category', 'code', 'description', 'value', 'units', 'type']) | 0 | 1 |
| pred_sql_error: ProgrammingError: Incorrect number of bindings supplied. The current statement uses 3, and there are 0 supplied. | 1 | 0 |
| column_count_mismatch gold=2 pred=3 (gold_cols=['code', 'patient_count'] pred_cols=['diagnosis_code', 'diagnosis_description', 'encounter_count']) | 0 | 1 |
| column_count_mismatch gold=8 pred=17 (gold_cols=['start', 'stop', 'patient', 'encounter', 'code', 'description', 'reasoncode', 'reasondescription'] pred_cols=['start', 'stop', 'code', 'description', 'reasoncode', 'reasondescription', 'ENCOUNTER_ID', 'ENCOUNTER_START', 'ENCOUNTER_STOP', 'organization', 'provider', 'payer', 'encounterclass', 'ENCOUNTER_CODE', 'ENCOUNTER_DESCRIPTION', 'ENCOUNTER_REASONCODE', 'ENCOUNTER_REASONDESCRIPTION']) | 0 | 1 |
| pred_sql_error: OperationalError: unrecognized token: "00126cb9" | 0 | 1 |
| missing_rows=1; extra_rows=18; alias_differs: gold=['start', 'stop', 'patient', 'encounter', 'code', 'description'] pred=['code', 'description', 'start', 'stop', 'patient', 'encounter'] | 0 | 1 |

## 5. v1 → v2 시나리오별 변화

| 분류 | 개수 | scenario_id |
|---|---|---|
| ✅→✅ 둘 다 정답 | 40 | 40건 |
| 🔺 v1오답→v2정답 (개선) | 7 | attending_physician_001, external_auditor_001, external_auditor_003, hospital_director_001, nurse_001, privacy_officer_001, system_admin_001 |
| 🔻 v1정답→v2오답 (퇴보) | 7 | patient_001, patient_002, pharmacist_002, pharmacist_003, research_analyst_001, research_analyst_003, system_admin_002 |
| ❌→❌ 둘 다 오답 | 24 | attending_physician_002, clinical_technician_001, clinical_technician_002, clinical_technician_003, external_auditor_002, hospital_director_002, hospital_director_003, insurance_examiner_001, insurance_examiner_002, insurance_examiner_003, medical_coder_001, medical_coder_002, medical_coder_003, nurse_002, nurse_003, patient_003, pharmacist_001, privacy_officer_002, privacy_officer_003, registration_clerk_001, registration_clerk_002, registration_clerk_003, system_admin_003, system_admin_004 |

## 6. 여전히 오답인 케이스 (v2 기준 오답 상세)

| scenario_id | gold | pred | reason (v2) |
|---|---|---|---|
| attending_physician_002 | ALLOW | ALLOW | missing_rows=1; extra_rows=1 |
| clinical_technician_001 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| clinical_technician_002 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| clinical_technician_003 | ALLOW | ALLOW | column_count_mismatch gold=8 pred=17 (gold_cols=['start', 'stop', 'patient', 'encounter', 'code', 'description', 'reasoncode', 'reasondescription'] pred_cols=['start', 'stop', 'code', 'description', 'reasoncode', 'reasondescription', 'ENCOUNTER_ID', 'ENCOUNTER_START', 'ENCOUNTER_STOP', 'organization', 'provider', 'payer', 'encounterclass', 'ENCOUNTER_CODE', 'ENCOUNTER_DESCRIPTION', 'ENCOUNTER_REASONCODE', 'ENCOUNTER_REASONDESCRIPTION']) |
| external_auditor_002 | ALLOW | ALLOW | missing_rows=1163; extra_rows=1; alias_differs: gold=['patientid', 'total_payments', 'total_adjustments', 'total_transfers'] pred=['total_payments', 'total_adjustments', 'total_transfers', 'grand_total'] |
| hospital_director_002 | ALLOW | ALLOW | missing_rows=1; extra_rows=1 |
| hospital_director_003 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| insurance_examiner_001 | ALLOW | ALLOW | missing_rows=1; extra_rows=1 |
| insurance_examiner_002 | ALLOW | ALLOW | column_count_mismatch gold=33 pred=30 (gold_cols=['id', 'claimid', 'chargeid', 'patientid', 'type', 'amount', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'modifier1', 'modifier2', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'departmentid', 'notes', 'unitamount', 'transferoutid', 'transfertype', 'payments', 'adjustments', 'transfers', 'outstanding', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid'] pred_cols=['transaction_id', 'claimid', 'chargeid', 'transaction_type', 'line_amount', 'payments', 'adjustments', 'transfers', 'outstanding', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'modifier1', 'modifier2', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'unitamount', 'departmentid', 'notes', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid']) |
| insurance_examiner_003 | ALLOW | ALLOW | column_count_mismatch gold=4 pred=2 (gold_cols=['patient', 'encounter', 'code', 'description'] pred_cols=['code', 'description']) |
| medical_coder_001 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| medical_coder_002 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| medical_coder_003 | ALLOW | ALLOW | missing_rows=1; extra_rows=18; alias_differs: gold=['start', 'stop', 'patient', 'encounter', 'code', 'description'] pred=['code', 'description', 'start', 'stop', 'patient', 'encounter'] |
| nurse_002 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| nurse_003 | ALLOW | ALLOW | missing_rows=794 |
| patient_001 | ALLOW | ALLOW | missing_rows=39; extra_rows=172; alias_differs: gold=['start', 'stop', 'patient', 'payer', 'encounter', 'code', 'description', 'base_cost', 'payer_coverage', 'dispenses', 'totalcost', 'reasoncode', 'reasondescription'] pred=['record_type', 'record_start', 'record_stop', 'code', 'description', 'payer', 'dispenses', 'totalcost', 'reasoncode', 'reasondescription', 'encounter_id', 'encounter_start', 'encounter_stop'] |
| patient_002 | ALLOW | ALLOW | column_count_mismatch gold=9 pred=8 (gold_cols=['date', 'patient', 'encounter', 'category', 'code', 'description', 'value', 'units', 'type'] pred_cols=['date', 'encounter', 'category', 'code', 'description', 'value', 'units', 'type']) |
| patient_003 | ALLOW | ALLOW | column_count_mismatch gold=9 pred=29 (gold_cols=['id', 'patientid', 'providerid', 'status1', 'status2', 'statusp', 'outstanding1', 'outstanding2', 'outstandingp'] pred_cols=['id', 'patientid', 'providerid', 'primarypatientinsuranceid', 'secondarypatientinsuranceid', 'departmentid', 'patientdepartmentid', 'diagnosis1', 'diagnosis2', 'diagnosis3', 'diagnosis4', 'diagnosis5', 'diagnosis6', 'diagnosis7', 'diagnosis8', 'appointmentid', 'currentillnessdate', 'servicedate', 'status1', 'status2', 'statusp', 'outstanding1', 'outstanding2', 'outstandingp', 'lastbilleddate1', 'lastbilleddate2', 'lastbilleddatep', 'healthcareclaimtypeid1', 'healthcareclaimtypeid2']) |
| pharmacist_001 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| pharmacist_002 | ALLOW | ALLOW | missing_rows=794 |
| pharmacist_003 | ALLOW | ALLOW | missing_rows=38076 |
| privacy_officer_002 | ALLOW | ALLOW | pred_sql_error: OperationalError: unrecognized token: "00126cb9" |
| privacy_officer_003 | ALLOW | ALLOW | column_count_mismatch gold=33 pred=29 (gold_cols=['id', 'claimid', 'chargeid', 'patientid', 'type', 'amount', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'modifier1', 'modifier2', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'departmentid', 'notes', 'unitamount', 'transferoutid', 'transfertype', 'payments', 'adjustments', 'transfers', 'outstanding', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid'] pred_cols=['transaction_id', 'claimid', 'chargeid', 'patientid', 'type', 'amount', 'method', 'fromdate', 'todate', 'placeofservice', 'procedurecode', 'diagnosisref1', 'diagnosisref2', 'diagnosisref3', 'diagnosisref4', 'units', 'departmentid', 'notes', 'unitamount', 'payments', 'adjustments', 'transfers', 'outstanding', 'appointmentid', 'linenote', 'patientinsuranceid', 'feescheduleid', 'providerid', 'supervisingproviderid']) |
| registration_clerk_001 | ALLOW | ALLOW | pred_sql_error: IntegrityError: UNIQUE constraint failed: patients.id |
| registration_clerk_002 | ALLOW | ALLOW | missing_rows=1; extra_rows=1 |
| registration_clerk_003 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| research_analyst_001 | ALLOW | ALLOW | column_count_mismatch gold=2 pred=3 (gold_cols=['code', 'patient_count'] pred_cols=['diagnosis_code', 'diagnosis_description', 'encounter_count']) |
| research_analyst_003 | ALLOW | ALLOW | column_count_mismatch gold=2 pred=4 (gold_cols=['code', 'avg_totalcost'] pred_cols=['medication_code', 'medication_description', 'medication_record_count', 'avg_totalcost']) |
| system_admin_002 | ALLOW | ALLOW | pred_sql_error: IntegrityError: UNIQUE constraint failed: patients.id |
| system_admin_003 | ALLOW | DENY | status_mismatch (gold=ALLOW pred=DENY) |
| system_admin_004 | ALLOW | ALLOW | missing_rows=1; extra_rows=1 |
