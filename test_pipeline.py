import csv
from pathlib import Path
import tempfile
import unittest
from pipeline import FIELDS, database_rows, inspect_csv, normalize, run
from run_demo import demo, save_csv


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.csv"
        self.db = self.root / "warehouse.sqlite"

    def rows(self, n=5):
        return [[f"id-{i}", "2026-01-15", "2", "12.50"] for i in range(n)]

    def execute(self, rows, name="run"):
        save_csv(self.source, rows)
        return run(self.source, self.db, self.root / name)

    def test_valid_load_and_exact_money(self):
        result = self.execute(self.rows())
        self.assertEqual(result["inserted"], 5)
        self.assertEqual(database_rows(self.db)[0][3], 1250)

    def test_missing_and_impossible_date_quarantined(self):
        rows = self.rows()
        rows[0][1], rows[1][2] = "2026-02-30", ""
        result = self.execute(rows)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["rejected_records"], 2)
        self.assertFalse(self.db.exists())

    def test_threshold_boundary_loads_only_valid(self):
        rows = self.rows()
        rows[0][2] = "0"
        result = self.execute(rows)
        self.assertEqual(result["error_rate"], .2)
        self.assertEqual(result["inserted"], 4)

    def test_all_duplicate_occurrences_rejected(self):
        rows = self.rows(10)
        rows[1][0] = rows[0][0]
        result = self.execute(rows)
        self.assertEqual(result["rejected_records"], 2)
        self.assertEqual(result["inserted"], 8)
        self.assertNotIn("id-0", [r[0] for r in database_rows(self.db)])

    def test_duplicate_with_invalid_occurrence_rejects_good_too(self):
        rows = self.rows()
        rows[1][0], rows[1][2] = rows[0][0], ""
        result = self.execute(rows)
        self.assertEqual(result["rejected_records"], 2)

    def test_replay_has_no_duplicates(self):
        self.execute(self.rows(), "first")
        result = self.execute(self.rows(), "second")
        self.assertEqual((result["inserted"], result["skipped"]), (0, 5))
        self.assertEqual(len(database_rows(self.db)), 5)

    def test_conflict_rolls_back_earlier_insert(self):
        self.execute(self.rows(), "first")
        before = database_rows(self.db)
        result = self.execute([["new", "2026-01-15", "1", "1.00"],
                               ["id-0", "2026-01-15", "99", "12.50"]], "conflict")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(database_rows(self.db), before)

    def test_header_and_empty_data_fail_closed(self):
        for i, text in enumerate(["", ",".join(FIELDS) + "\n", "id,date\n1,2026-01-01\n"]):
            self.source.write_text(text)
            result = run(self.source, self.db, self.root / str(i))
            self.assertEqual(result["status"], "blocked")
        self.assertFalse(self.db.exists())

    def test_extra_and_missing_columns(self):
        rows = self.rows()
        rows[0].append("extra")
        rows[1].pop()
        result = self.execute(rows)
        self.assertEqual(result["rejected_records"], 2)

    def test_invalid_numeric_values(self):
        row = dict(zip(FIELDS, self.rows()[0]))
        for price in ["NaN", "Infinity", "-1", "0.001", "1000001", "abc", "0.010000000000000000000000000001"]:
            with self.subTest(price=price), self.assertRaises(ValueError):
                normalize({**row, "unit_price": price})
        for quantity in ["1.5", "10001", "-1", "True"]:
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                normalize({**row, "quantity": quantity})

    def test_whitespace_and_bom(self):
        rows = self.rows()
        rows[0][0] = " id-0 "
        save_csv(self.source, rows)
        self.source.write_bytes(b"\xef\xbb\xbf" + self.source.read_bytes())
        valid, rejected, total, fatal = inspect_csv(self.source)
        self.assertEqual(valid[0]["normalized"]["order_id"], "id-0")
        self.assertEqual((len(rejected), total, fatal), (0, 5, []))

    def test_malformed_csv_and_encoding_block(self):
        for i, payload in enumerate([b'order_id,order_date,quantity,unit_price\n"unterminated',
                                     b'order_id,order_date,quantity,unit_price\n\xff']):
            self.source.write_bytes(payload)
            result = run(self.source, self.db, self.root / str(i))
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(result["fatal_errors"])

    def test_output_cannot_overwrite_evidence(self):
        self.execute(self.rows())
        with self.assertRaises(ValueError):
            self.execute(self.rows())

    def test_complete_recovery_demo(self):
        result = demo(self.root / "demo")
        self.assertEqual(result["final_rows"], 10)
        self.assertEqual([p["status"] for p in result["phases"]],
                         ["blocked", "loaded", "loaded", "blocked", "loaded"])


if __name__ == "__main__":
    unittest.main()
