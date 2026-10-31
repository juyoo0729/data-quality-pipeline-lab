# 실행과 복구

## 1. 전체 실험
```bash
python -m unittest -v
python run_demo.py --output runs/my-first-run
```
summary.md와 summary.json에서 5단계를 확인합니다. 데이터는 실행 시 직접 생성됩니다.

## 2. 품질 차단
sample-bad.csv를 입력하면 10건 중 4건이 격리되어 오류율 40%로 차단됩니다.
```bash
python pipeline.py sample-bad.csv --db runs/manual.sqlite --output runs/manual-bad
```
종료 코드 2는 이 실습에서 예상한 차단 결과입니다.
quarantine.jsonl을 보고 잘못된 날짜·수량과 중복 ID를 확인합니다.

## 3. 수정 후 재실행
```bash
python pipeline.py sample-corrected.csv --db runs/manual.sqlite --output runs/manual-fixed
python pipeline.py sample-corrected.csv --db runs/manual.sqlite --output runs/manual-replay
```
처음에는 inserted=10, 두 번째는 inserted=0 및 skipped=10이어야 합니다.

## 4. 저장된 ID와의 충돌
전체 실험의 04-conflict/report.json에서 destination_conflict를 확인합니다.
그 실행에서 앞서 넣었던 신규 행도 함께 롤백됩니다.
기존 데이터가 맞다면 입력을 고친 뒤 새 결과 폴더로 실행합니다.
기존 데이터 자체가 틀렸다면 자동 덮어쓰기 대신 별도의 정정 정책을 설계해야 합니다.

## 5. 직접 바꿔볼 실험
- 10건 중 오류 2건과 3건을 비교해 정확히 20%와 초과의 차이를 확인하기.
- 동일 ID의 내용이 같아도 파일 내부에서는 모두 격리되는 이유 설명하기.
- CSV 순서를 바꿔도 중복 ID를 임의로 하나 선택하지 않는지 확인하기.
- 정상 적재 뒤 같은 파일을 여러 번 실행해 DB 행 수 확인하기.

결과 폴더는 매번 새 이름으로 사용합니다. 원본 오류 CSV는 직접 수정하지 않고 수정본을 별도로 남기는 편이 비교하기 쉽습니다.
