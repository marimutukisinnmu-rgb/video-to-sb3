from __future__ import annotations
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from video_to_sb3.player import build_player_sb3, build_project_json

class PlayerBuilderTests(unittest.TestCase):
    def test_project_is_minimal_and_external_video_only(self):
        project = build_project_json()
        self.assertEqual(project["extensions"], ["vtsb3player"])
        self.assertEqual(project["targets"][0]["costumes"][0]["name"], "blank")
        self.assertEqual(project["targets"][0]["sounds"], [])
        self.assertEqual(project["targets"][0]["blocks"], {})
        self.assertIn("vtsb3player", project["extensionURLs"])
        self.assertNotIn("output.vtsb3", json.dumps(project))
        self.assertEqual(len(project["targets"]), 1)
        self.assertTrue(project["targets"][0]["isStage"])

    def test_rejects_non_unsandboxed_extension_url(self):
        with self.assertRaises(ValueError):
            build_project_json("https://example.com/ext.js")

    def test_sb3_is_valid_and_small(self):
        with tempfile.TemporaryDirectory() as directory:
            path = build_player_sb3(Path(directory) / "player.sb3")
            self.assertLess(path.stat().st_size, 3 * 1024 * 1024)
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                project = json.loads(archive.read("project.json"))
                self.assertEqual(project["extensions"], ["vtsb3player"])
                self.assertEqual(len(project["targets"]), 1)

if __name__ == "__main__":
    unittest.main()
