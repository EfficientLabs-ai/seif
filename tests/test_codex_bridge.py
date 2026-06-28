import json
import os
import tempfile
import unittest
from pathlib import Path

from bridge.codex_seif_ecp_bridge import build_packet, write_result_packet


class TestCodexBridge(unittest.TestCase):
    def make_repo(self):
        root = Path(tempfile.mkdtemp(prefix="codex-bridge-"))
        (root / "docs").mkdir()
        (root / "docs" / "safe.md").write_text("safe doctrine", encoding="utf-8")
        (root / ".env").write_text("TOKEN=secret", encoding="utf-8")
        (root / "vault").mkdir()
        (root / "vault" / "secret.txt").write_text("secret", encoding="utf-8")
        outside = root.parent / (root.name + "-outside.txt")
        outside.write_text("outside", encoding="utf-8")
        try:
            os.symlink(outside, root / "docs" / "leak.md")
        except OSError:
            pass
        return root

    def test_packet_includes_safe_doc_and_excludes_secret_paths(self):
        repo = self.make_repo()
        packet = build_packet({
            "repo": str(repo),
            "issue_id": 7,
            "branch": "codex/test",
            "docs": ["docs/safe.md", ".env", "vault/secret.txt", "../escape.md", "docs/leak.md"],
            "test_commands": ["npm test"],
        })
        self.assertEqual(packet["schema"], "codex.seif.ecp.task.v1")
        self.assertEqual([d["path"] for d in packet["included_docs"]], ["docs/safe.md"])
        excluded = {d["path"]: d["reason"] for d in packet["excluded_docs"]}
        self.assertIn(".env", excluded)
        self.assertIn("vault/secret.txt", excluded)
        self.assertIn("../escape.md", excluded)
        if "docs/leak.md" in excluded:
            self.assertIn("symlink", excluded["docs/leak.md"])
        self.assertEqual(len(packet["receipt_hash"]), 64)

    def test_receipt_hash_is_deterministic(self):
        repo = self.make_repo()
        req = {"repo": str(repo), "docs": ["docs/safe.md"], "test_commands": ["true"]}
        self.assertEqual(build_packet(req)["receipt_hash"], build_packet(req)["receipt_hash"])

    def test_result_packet_links_task_receipt(self):
        repo = self.make_repo()
        task = build_packet({"repo": str(repo), "docs": ["docs/safe.md"]})
        result = write_result_packet(task, {"commands": ["true"], "tests": [{"cmd": "true", "ok": True}]})
        self.assertEqual(result["task_receipt_hash"], task["receipt_hash"])
        self.assertEqual(result["schema"], "codex.seif.ecp.result.v1")
        self.assertEqual(len(result["receipt_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
