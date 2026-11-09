"""Export only the bundled synthetic dataset from a fresh database for GitHub Pages."""
import json
import os
import tempfile
from pathlib import Path

from app import db, engine, main
from app.cli import evaluate


def export(output):
    output.mkdir(parents=True, exist_ok=True)

    def write(name, value):
        target = output / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="reconcile-demo-") as directory:
        os.environ["RECON_DB"] = str(Path(directory) / "synthetic.sqlite3")
        db.seed()
        engine.run()
        assert evaluate()["all_passed"], "Synthetic baseline differs from expected results"
        summary = main.summary()
        write("reconciliations/summary", summary)
        write("runs", main.runs())
        write("imports", main.imports())
        cases = main.exceptions(offset=0, limit=100_000)["items"]
        write("exceptions", cases)
        for case in cases:
            write(f"exceptions/{case['id']}", main.case_detail(case["id"]))
        write("checks", main.checks(offset=0, limit=100_000)["items"])
        for table in db.SOURCE_TABLES:
            write(f"sources/{table}", main.source(table, offset=0, limit=1_000_000))
        (output / "exceptions.csv").write_bytes(main.export().body)


if __name__ == "__main__":
    export(db.ROOT / "frontend/demo-dist/snapshot")
