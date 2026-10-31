"""Deterministic bad -> corrected -> replay -> conflict recovery exercise."""
from pathlib import Path
import argparse
import csv
import platform
from pipeline import FIELDS, database_rows, run, write_json


def save_csv(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        writer.writerows(rows)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def demo(output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("use a new output directory")
    output.mkdir(parents=True, exist_ok=True)
    good = [[f"ORDER-{i:03d}", "2026-01-15", "2", "12.50"] for i in range(1, 11)]
    bad = [row[:] for row in good]
    bad[0][1] = "2026-02-30"
    bad[1][2] = ""
    bad[2][0] = bad[3][0]
    save_csv(output / "bad.csv", bad)
    save_csv(output / "corrected.csv", good)
    # The new row comes first: its insert must roll back if a later ID conflicts.
    conflict = [["ORDER-NEW", "2026-01-15", "1", "1.00"], [*good[0][:2], "99", "12.50"]]
    save_csv(output / "conflict.csv", conflict)
    db = output / "warehouse.sqlite"
    phases = []
    phases.append(run(output / "bad.csv", db, output / "01-blocked"))
    require(phases[-1]["status"] == "blocked" and not database_rows(db), "bad batch was loaded")
    phases.append(run(output / "corrected.csv", db, output / "02-corrected"))
    require(phases[-1]["inserted"] == 10, "corrected batch failed")
    snapshot = database_rows(db)
    phases.append(run(output / "corrected.csv", db, output / "03-replay"))
    require(phases[-1]["skipped"] == 10 and database_rows(db) == snapshot, "replay duplicated data")
    phases.append(run(output / "conflict.csv", db, output / "04-conflict"))
    require(phases[-1]["status"] == "blocked" and database_rows(db) == snapshot, "partial transaction leaked")
    phases.append(run(output / "corrected.csv", db, output / "05-recovery"))
    require(phases[-1]["skipped"] == 10 and database_rows(db) == snapshot, "recovery changed rows")
    result = {"python": platform.python_version(), "final_rows": len(snapshot), "phases": phases}
    write_json(output / "summary.json", result)
    lines = ["# Data quality and recovery experiment", "",
             "| Phase | Status | Valid | Quarantine | Inserted | Skipped |",
             "|---|---|---:|---:|---:|---:|"]
    for name, report in zip(["bad", "corrected", "replay", "conflict", "recovery"], phases):
        lines.append(f'| {name} | {report["status"]} | {report["valid_records"]} | '
                     f'{report["rejected_records"]} | {report["inserted"]} | {report["skipped"]} |')
    lines += ["", f"Final persisted rows: {len(snapshot)}.",
              "Conflict rollback preserved the complete previously loaded dataset.",
              "All inputs are synthetic. No real customer data."]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="runs/local-01")
    args = parser.parse_args()
    result = demo(args.output)
    print(f'Completed: {len(result["phases"])} phases, {result["final_rows"]} rows')
