"""Dataset generator with a fake LLM client: dedup, noise injection, output files."""

import csv
import json
from collections import Counter
from pathlib import Path

from app.config import Settings
from scripts import generate_dataset as gen
from tests.fakes import FakeLlmClient, load_fixture

FIXTURE = load_fixture("dataset_batch.json")
CLEAN_IN_FIXTURE = 12  # 13 entries, the last one is a case variant of the first


def run(tmp_path: Path) -> tuple[FakeLlmClient, list[gen.Row]]:
    client = FakeLlmClient(tool_payloads={"record_verbatims": [FIXTURE]})
    rows = gen.generate(client, Settings(), tmp_path, batch_count=2, batch_size=13, min_total=20)
    return client, rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_deduplicates_across_batches_and_adds_a_complement_batch(tmp_path: Path) -> None:
    client, rows = run(tmp_path)
    # 2 batches + 1 complement (12 unique < min_total=20), all with the same fixture.
    assert [c["user"] for c in client.calls] == [
        "Lot 1 sur 2. Produis 13 verbatims.",
        "Lot 2 sur 2. Produis 13 verbatims.",
        "Lot 3 sur 3. Produis 13 verbatims.",
    ]
    assert sum(1 for r in rows if not r.noise) == CLEAN_IN_FIXTURE


def test_injects_the_expected_noise(tmp_path: Path) -> None:
    _, rows = run(tmp_path)
    assert Counter(r.noise for r in rows if r.noise) == {
        "empty": 5,
        "ras": 5,
        "duplicate": 6,
        "whitespace": 4,
    }
    assert len(rows) == CLEAN_IN_FIXTURE + 20
    for row in rows:
        if row.source is not None:
            assert gen.normalize(row.text) == gen.normalize(row.source.text)
            assert row.source.id < row.id, "the original must come before its copy"
            assert row.expected_sentiment == row.source.expected_sentiment


def test_writes_input_gold_and_log_files(tmp_path: Path) -> None:
    client, rows = run(tmp_path)
    raw = (tmp_path / gen.INPUT_FILE).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "no BOM"

    inputs = read_csv(tmp_path / gen.INPUT_FILE)
    gold = read_csv(tmp_path / gen.GOLD_FILE)
    assert [r["id"] for r in inputs] == [str(i) for i in range(1, len(rows) + 1)]
    assert [r["id"] for r in gold] == [r["id"] for r in inputs]
    assert set(inputs[0]) == {"id", "verbatim"}, "labels never reach the pipeline input"

    by_id = {r["id"]: r for r in inputs}
    for g in gold:
        if g["noise"].startswith("duplicate_of:"):
            original = g["noise"].split(":")[1]
            assert by_id[g["id"]]["verbatim"] == by_id[original]["verbatim"]

    log = json.loads((tmp_path / gen.LOG_FILE).read_text(encoding="utf-8"))
    assert log["rows"] == len(rows) and len(log["calls"]) == len(client.usage)


def test_generation_is_reproducible(tmp_path: Path) -> None:
    run(tmp_path / "a")
    run(tmp_path / "b")
    first = (tmp_path / "a" / gen.INPUT_FILE).read_text(encoding="utf-8")
    assert first == (tmp_path / "b" / gen.INPUT_FILE).read_text(encoding="utf-8")


def test_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    (tmp_path / gen.INPUT_FILE).write_text("id,verbatim\n", encoding="utf-8")
    assert gen.main(["--out-dir", str(tmp_path)]) == 1
    assert (tmp_path / gen.INPUT_FILE).read_text(encoding="utf-8") == "id,verbatim\n"
