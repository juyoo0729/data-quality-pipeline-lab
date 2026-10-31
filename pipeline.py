"""CSV quality gate and idempotent SQLite loader. Standard library only."""
import argparse
from contextlib import closing
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3

FIELDS = ["order_id", "order_date", "quantity", "unit_price"]
MAX_ERROR_RATE = Decimal("0.20")


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(row):
    if set(row) != set(FIELDS) or any(not isinstance(row[k], str) for k in FIELDS):
        raise ValueError("column_count")
    row = {key: value.strip() for key, value in row.items()}
    if not row["order_id"] or len(row["order_id"]) > 64:
        raise ValueError("order_id")
    # ASCII format is part of the contract, not a permissive date parser.
    value = row["order_date"]
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError("order_date")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise ValueError("order_date") from None
    quantity = row["quantity"]
    if not quantity.isascii() or not quantity.isdigit() or not 1 <= int(quantity) <= 10000:
        raise ValueError("quantity")
    try:
        price = Decimal(row["unit_price"])
        if not price.is_finite() or price < 0 or price > Decimal("1000000"):
            raise ValueError("unit_price")
        if price != price.quantize(Decimal("0.01")):
            raise ValueError("unit_price_precision")
        cents = price * 100
    except InvalidOperation:
        raise ValueError("unit_price") from None
    return {"order_id": row["order_id"], "order_date": value,
            "quantity": int(quantity), "unit_price_cents": int(cents)}


def inspect_csv(path):
    valid, rejected, fatal = [], [], []
    total = 0
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames != FIELDS:
                return [], [], 0, ["header: expected " + ",".join(FIELDS)]
            for total, row in enumerate(reader, 1):
                record = {"record": total, "raw": row}
                try:
                    record["normalized"] = normalize(row)
                    valid.append(record)
                except ValueError as exc:
                    rejected.append({**record, "reason": str(exc)})
    except (UnicodeError, csv.Error) as exc:
        fatal.append("csv_parse: " + str(exc))
    if not total:
        fatal.append("empty_dataset")
    # Reject ALL occurrences of duplicated IDs, including invalid occurrences.
    # This avoids choosing a winner based on file order.
    counts = {}
    for item in valid + rejected:
        key = item["raw"].get("order_id")
        if isinstance(key, str) and key.strip():
            key = key.strip()
            counts[key] = counts.get(key, 0) + 1
    unique = []
    for item in valid:
        if counts[item["normalized"]["order_id"]] > 1:
            rejected.append({**item, "reason": "duplicate_order_id"})
        else:
            unique.append(item)
    return unique, sorted(rejected, key=lambda r: r["record"]), total, fatal


def database_rows(db_path):
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute(
            "SELECT order_id,order_date,quantity,unit_price_cents FROM orders ORDER BY order_id"
        ).fetchall()


def load_atomic(db_path, rows):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    inserted = skipped = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, order_date TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0))""")
        for row in rows:
            value = (row["order_date"], row["quantity"], row["unit_price_cents"])
            old = connection.execute(
                "SELECT order_date,quantity,unit_price_cents FROM orders WHERE order_id=?",
                (row["order_id"],)).fetchone()
            if old is None:
                connection.execute("INSERT INTO orders VALUES (?,?,?,?)", (row["order_id"], *value))
                inserted += 1
            elif old == value:
                skipped += 1
            else:
                raise ValueError("destination_conflict:" + row["order_id"])
        connection.commit()
        return inserted, skipped
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def run(source, db_path, output):
    source, db_path, output = Path(source), Path(db_path), Path(output)
    if not source.is_file():
        raise ValueError("source must exist")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    valid, rejected, total, fatal = inspect_csv(source)
    rate = Decimal(len(rejected)) / total if total else Decimal(1)
    report = {"source_file": source.name, "source_sha256": fingerprint(source),
              "code_sha256": fingerprint(__file__), "total_records": total,
              "valid_records": len(valid), "rejected_records": len(rejected),
              "error_rate": float(rate), "max_error_rate": float(MAX_ERROR_RATE),
              "fatal_errors": fatal, "status": "blocked", "inserted": 0, "skipped": 0}
    # These files are diagnostic candidates, not evidence of a successful load.
    with (output / "valid.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["order_id", "order_date", "quantity", "unit_price_cents"])
        writer.writeheader()
        writer.writerows(item["normalized"] for item in valid)
    with (output / "quarantine.jsonl").open("w", encoding="utf-8") as stream:
        for item in rejected:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    if not fatal and valid and rate <= MAX_ERROR_RATE:
        try:
            inserted, skipped = load_atomic(db_path, [item["normalized"] for item in valid])
            report.update(status="loaded", inserted=inserted, skipped=skipped)
        except ValueError as exc:
            report["fatal_errors"].append(str(exc))
    elif not valid and not fatal:
        report["fatal_errors"].append("no_valid_records")
    write_json(output / "report.json", report)
    (output / "report.md").write_text(
        "# Data quality run\n\n"
        + "\n".join(f"- {key}: {value}" for key, value in report.items()) + "\n",
        encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.source, args.db, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "loaded" else 2)
