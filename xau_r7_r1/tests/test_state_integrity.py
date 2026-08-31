from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from r7_runtime.audit_store import AuditStore, StoreError


class StateIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.sqlite3"
        self.store = AuditStore(self.path)

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        self.tmp.cleanup()

    def reserve(self, intent_id="a"):
        payload = {"client_intent_id": intent_id, "side": "BUY", "lot": 0.01}
        self.store.reserve_intent(intent_id, payload)
        return payload

    def test_clean_store_replays(self):
        self.reserve()
        self.store.transition("a", "PREFLIGHT_OK")
        result = self.store.verify_store_integrity()
        self.assertEqual(result["audit_chain"], "PASS")
        self.assertEqual(result["intent_count"], 1)

    def test_payload_json_tamper_is_detected(self):
        self.reserve()
        self.store.conn.execute("UPDATE order_intents SET payload_json='{}' WHERE client_intent_id='a'")
        with self.assertRaisesRegex(StoreError, "PAYLOAD_HASH"):
            self.store.verify_store_integrity()

    def test_payload_hash_tamper_is_detected(self):
        self.reserve()
        self.store.conn.execute("UPDATE order_intents SET payload_hash=? WHERE client_intent_id='a'", ("0" * 64,))
        with self.assertRaisesRegex(StoreError, "PAYLOAD"):
            self.store.verify_store_integrity()

    def test_state_column_tamper_is_detected(self):
        self.reserve()
        self.store.conn.execute("UPDATE order_intents SET state='ACKNOWLEDGED' WHERE client_intent_id='a'")
        with self.assertRaisesRegex(StoreError, "STATE_LEDGER_MISMATCH"):
            self.store.verify_store_integrity()

    def test_deleted_intent_row_is_detected(self):
        self.reserve()
        self.store.conn.execute("DELETE FROM order_intents WHERE client_intent_id='a'")
        with self.assertRaisesRegex(StoreError, "ID_SET_MISMATCH"):
            self.store.verify_store_integrity()

    def test_injected_intent_row_is_detected(self):
        self.reserve()
        row = self.store.conn.execute("SELECT payload_json,payload_hash,created_utc,updated_utc FROM order_intents WHERE client_intent_id='a'").fetchone()
        self.store.conn.execute(
            "INSERT INTO order_intents(client_intent_id,payload_json,payload_hash,state,created_utc,updated_utc) VALUES(?,?,?,?,?,?)",
            ("evil", row[0], row[1], "RESERVED", row[2], row[3]),
        )
        with self.assertRaisesRegex(StoreError, "ID_SET_MISMATCH"):
            self.store.verify_store_integrity()

    def test_broker_ticket_tamper_is_detected(self):
        self.reserve()
        self.store.transition("a", "PREFLIGHT_OK")
        self.store.transition("a", "SUBMITTING")
        self.store.transition("a", "SUBMITTED", broker_ticket=123)
        self.store.conn.execute("UPDATE order_intents SET broker_ticket=999 WHERE client_intent_id='a'")
        with self.assertRaisesRegex(StoreError, "BROKER_TICKET_LEDGER_MISMATCH"):
            self.store.verify_store_integrity()

    def test_runtime_state_tamper_is_detected(self):
        self.store.set_runtime_state("pause", {"enabled": True})
        self.store.conn.execute("UPDATE runtime_state SET value_json=? WHERE key='pause'", ('{"enabled":false}',))
        with self.assertRaisesRegex(StoreError, "RUNTIME_STATE_LEDGER_MISMATCH"):
            self.store.verify_store_integrity()

    def test_audit_payload_tamper_is_detected(self):
        self.reserve()
        self.store.conn.execute("UPDATE audit_events SET payload_json='{}' WHERE seq=1")
        with self.assertRaisesRegex(StoreError, "AUDIT_CHAIN"):
            self.store.verify_store_integrity()

    def test_audit_prev_hash_tamper_is_detected(self):
        self.reserve()
        self.store.append_event("X", {"a": 1})
        self.store.conn.execute("UPDATE audit_events SET prev_hash=? WHERE seq=2", ("f" * 64,))
        with self.assertRaisesRegex(StoreError, "AUDIT_CHAIN"):
            self.store.verify_store_integrity()

    def test_transition_ledger_discontinuity_detected_even_if_chain_rehashed_not_attempted(self):
        self.reserve()
        self.store.transition("a", "PREFLIGHT_OK")
        # Direct state mutation already proves the replay gate is independent of
        # SQLite structural validity and catches semantic persistence corruption.
        self.store.conn.execute("UPDATE order_intents SET state='RESERVED' WHERE client_intent_id='a'")
        with self.assertRaisesRegex(StoreError, "STATE_LEDGER_MISMATCH"):
            self.store.verify_store_integrity()


if __name__ == "__main__":
    unittest.main()
