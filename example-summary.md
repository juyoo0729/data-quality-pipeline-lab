# Data quality and recovery experiment

| Phase | Status | Valid | Quarantine | Inserted | Skipped |
|---|---|---:|---:|---:|---:|
| bad | blocked | 6 | 4 | 0 | 0 |
| corrected | loaded | 10 | 0 | 10 | 0 |
| replay | loaded | 10 | 0 | 0 | 10 |
| conflict | blocked | 2 | 0 | 0 | 0 |
| recovery | loaded | 10 | 0 | 0 | 10 |

Final persisted rows: 10.
Conflict rollback preserved the complete previously loaded dataset.
All inputs are synthetic. No real customer data.
