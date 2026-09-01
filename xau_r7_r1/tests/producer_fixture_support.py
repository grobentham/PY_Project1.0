from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from r7_runtime.constants import (
    CANONICAL_R6_ZIP_SHA256,
    R6_DECISION_POLICY,
    R6_DECISION_SCHEMA,
    R6_SOURCE_PRIORITY,
)
from r7_runtime.r6_integrity import sha256_file
from r7_runtime.r6_producer_parity import ISOLATION_SCHEMA, build_parity_report
from r7_runtime.r6_producer_replay import FIXTURE_SCHEMA, replay_producer
from r7_runtime.r6_source_bundle import BUNDLE_VERSION
from r7_runtime.r6_source_probe import probe_frozen_r6_source


def decision(source: str, i: int) -> Dict[str, object]:
    signal = 1_700_000_000_000 + i * 60_000
    emitted = signal + 1_000
    return {
        "schema": R6_DECISION_SCHEMA,
        "policy": R6_DECISION_POLICY,
        "parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "decision_id": "trusted_fixture_" + str(i),
        "signal_bar_ms": signal,
        "emitted_at_ms": emitted,
        "side": 1 if i % 2 == 0 else -1,
        "source": source,
        "priority": R6_SOURCE_PRIORITY[source],
        "family": "BASE" if source == "CORE" else "FAMILY_" + source,
        "signal_type": "BASE_SIGNAL" if source == "CORE" else "SIGNAL_" + source,
        "atr_usd": 2.0 + i / 10.0,
        "stop_atr": 1.0,
        "target_atr": 2.0,
        "geometry_used": "PRIMARY",
        "lot_size": 0.01,
        "admitted": True,
    }


def _canonical_jsonl(rows) -> bytes:
    text = "\n".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows
    ) + "\n"
    return text.encode("utf-8")


def build_trusted_fixture(root: Path) -> Dict[str, Path]:
    root = Path(root)
    sources = {
        "v16r6/engine.py": (
            'RETIRED_SOURCE = "AUX_RF_LTM"\n'
            'def build_r6_universe(root):\n    return root\n\n'
            'def build_r6(root, **kwargs):\n    return root, kwargs\n'
        ),
        "v16r5/engine.py": (
            'def build_r5_universe(root):\n    return root\n\n'
            'def simulate_r5(universe, **kwargs):\n    return universe\n\n'
            'def summary(value):\n    return value\n\n'
            'def component_audit(value):\n    return value\n'
        ),
        "V16_R5_MAIN.py": 'FROZEN = True\n',
    }
    for relative, text in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    source_hashes = {relative: sha256_file(root / relative) for relative in sources}
    parent = {
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "build_verified_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "protected_r6_hashes": dict(source_hashes),
        "parent_tree_sha256": dict(source_hashes),
    }
    parent_path = root / "R7_R1_PARENT_INTEGRITY.json"
    parent_path.write_text(json.dumps(parent, sort_keys=True), encoding="utf-8")

    probe_path = root / "R7_R1_R6_SOURCE_PROBE.json"
    probe_path.write_text(json.dumps(probe_frozen_r6_source(root), sort_keys=True), encoding="utf-8")

    bundle_path = root / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json"
    bundle_path.write_text(json.dumps({
        "bundle_version": BUNDLE_VERSION,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "source_only_bundle": True,
        "static_local_python_dependency_closure_extracted": True,
        "required_local_imports_resolved": True,
        "dynamic_imports_allowed": False,
        "dependency_count": len(sources),
        "required_source_files": list(sources),
        "dependency_closure_files": list(sources),
        "unresolved_nonarchive_imports": {},
        "strategy_executed": False,
        "strategy_retuned": False,
        "final_holdout_accessed": False,
        "producer_admitted": False,
        "files": {
            relative: {
                "sha256": source_hashes[relative],
                "size_bytes": (root / relative).stat().st_size,
                "required_entry_source": True,
            }
            for relative in sources
        },
        "source_probe_file": probe_path.name,
        "source_probe_sha256": sha256_file(probe_path),
    }, sort_keys=True), encoding="utf-8")

    producer_module = root / "r7_runtime" / "r6_causal_producer.py"
    producer_module.parent.mkdir(parents=True, exist_ok=True)
    producer_module.write_text(
        'def produce(prefix):\n'
        '    return prefix["decision"]\n',
        encoding="utf-8",
    )

    reference_rows = []
    fixture_rows = []
    ordered_sources = sorted(R6_SOURCE_PRIORITY, key=R6_SOURCE_PRIORITY.get)
    for i, source in enumerate(ordered_sources):
        d = decision(source, i)
        cutoff = int(d["emitted_at_ms"])
        fixture_id = "fx_" + str(i)
        reference_rows.append({"fixture_id": fixture_id, "available_through_ms": cutoff, "decision": d})
        fixture_rows.append({
            "schema": FIXTURE_SCHEMA,
            "fixture_id": fixture_id,
            "available_through_ms": cutoff,
            "producer_input": {"decision": d},
        })

    fixture_path = root / "R7_R1_R6_PARITY_FIXTURES.jsonl"
    fixture_path.write_text(
        "\n".join(json.dumps(x, sort_keys=True) for x in fixture_rows) + "\n",
        encoding="utf-8",
    )
    reference_path = root / "R7_R1_R6_REFERENCE_STREAM.jsonl"
    # Hash-bound canonical JSONL must be byte-identical across Linux and Windows.
    reference_path.write_bytes(_canonical_jsonl(reference_rows))

    producer_stream_path = root / "R7_R1_R6_PRODUCER_STREAM.jsonl"
    replay_path = root / "R7_R1_R6_PRODUCER_REPLAY.json"
    stream_bytes, replay = replay_producer(fixture_path, producer_module)
    producer_stream_path.write_bytes(stream_bytes)
    replay_path.write_text(json.dumps(replay, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    isolation_path = root / "R7_R1_R6_PARITY_ISOLATION.json"
    isolation_path.write_text(json.dumps({
        "schema": ISOLATION_SCHEMA,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "reference_stream_sha256": sha256_file(reference_path),
        "producer_stream_sha256": sha256_file(producer_stream_path),
        "fixture_corpus_sha256": sha256_file(fixture_path),
        "producer_replay_attestation_sha256": sha256_file(replay_path),
        "fixture_count": len(reference_rows),
        "causal_prefix_fixture_generation": True,
        "trusted_producer_replay": True,
        "producer_source_policy_pass": True,
        "future_rows_available_to_producer": False,
        "outcome_columns_present": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
    }, sort_keys=True), encoding="utf-8")

    parity = build_parity_report(
        reference_path,
        producer_stream_path,
        fixture_path=fixture_path,
        replay_attestation_path=replay_path,
        isolation_path=isolation_path,
        source_probe_path=probe_path,
        source_bundle_manifest_path=bundle_path,
        producer_module_path=producer_module,
        producer_module_relative="r7_runtime/r6_causal_producer.py",
    )
    parity_path = root / "R7_R1_R6_PRODUCER_PARITY.json"
    parity_path.write_text(json.dumps(parity, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "parent": parent_path,
        "probe": probe_path,
        "bundle": bundle_path,
        "producer_module": producer_module,
        "fixtures": fixture_path,
        "replay": replay_path,
        "reference": reference_path,
        "producer_stream": producer_stream_path,
        "isolation": isolation_path,
        "parity": parity_path,
    }
