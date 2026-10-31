# 데이터 계약

| 필드 | 규칙 | 저장 |
|---|---|---|
| order_id | 앞뒤 공백 제거 후 1~64자, 대소문자 구분 | 문자열 기본키 |
| order_date | YYYY-MM-DD, 실제 존재하는 날짜 | ISO 날짜 문자열 |
| quantity | ASCII 숫자, 정수 1~10000 | 정수 |
| unit_price | 유한 Decimal, 0~1000000, 100배가 정수 | unit_price_cents 정수 |

헤더는 이름뿐 아니라 순서까지 일치해야 합니다. 추가·누락 열은 행 오류입니다.
날짜의 미래 여부를 판단하는 업무 규칙은 없습니다.
단가의 과학적 표기 등 Decimal이 받아들이는 표현은 값·정밀도 검사를 통과하면 허용합니다.
실제 금액의 통화나 반올림 규칙을 정의한 계약이 아닙니다.

## 오류 분류

- order_id / order_date / quantity / unit_price / unit_price_precision: 값 오류
- column_count: 행의 열 개수 불일치
- duplicate_order_id: 같은 파일의 중복 ID
- header / empty_dataset / csv_parse: 파일 전체 차단
- destination_conflict: 기존 저장 ID와 값이 달라 전체 DB 작업 롤백

여러 오류가 있는 행은 첫 값 오류를 기록합니다. 오류 행의 ID도 중복 탐지에 포함합니다.
파일 내부 중복은 최초 행을 자동 선택하지 않습니다. 이미 값 오류로 격리한 행을 중복으로 다시 세지도 않습니다.

## 합격 기준

파싱 가능한 레코드가 있고 유효 후보가 1개 이상이며, 파일 전체 오류가 없고,
격리 비율이 0.20 이하일 때에만 DB 적재를 시도합니다.

차단된 실행의 valid.csv는 검사 결과이지 적재 완료 데이터가 아닙니다.
최종 적재 여부는 report.json의 status, inserted, skipped를 확인합니다.
