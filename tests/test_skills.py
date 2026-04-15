"""
tests/test_skills.py — Tests for capabilities/skills.py
"""
import unittest
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from capabilities.skills import SkillRegistry, SkillManifest, SkillDocument


class TestSkillRegistry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skills_dir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_skill(self, name, description, body):
        import shutil
        skill_dir = self.skills_dir / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        skill_dir.mkdir(parents=True)
        content = f"---\nname: {name}\ndescription: {description}\n---\n{body}"
        (skill_dir / "SKILL.md").write_text(content)

    def test_loads_skills_from_directory(self):
        self._make_skill("test_skill", "A test skill", "Body content here")
        registry = SkillRegistry(self.skills_dir)
        self.assertIn("test_skill", registry.documents)
        self.assertEqual(registry.documents["test_skill"].manifest.description, "A test skill")

    def test_describe_available(self):
        self._make_skill("skill_a", "Description A", "")
        self._make_skill("skill_b", "Description B", "")
        registry = SkillRegistry(self.skills_dir)
        desc = registry.describe_available()
        self.assertIn("skill_a", desc)
        self.assertIn("skill_b", desc)

    def test_load_full_text(self):
        self._make_skill("my_skill", "My skill", "Actual skill body\nwith content")
        registry = SkillRegistry(self.skills_dir)
        result = registry.load_full_text("my_skill")
        self.assertIn("Actual skill body", result)
        self.assertIn("<skill", result)

    def test_load_unknown_skill(self):
        registry = SkillRegistry(self.skills_dir)
        result = registry.load_full_text("does_not_exist")
        self.assertTrue(result.startswith("Error"))

    def test_reload(self):
        self._make_skill("reload_test", "Before", "old")
        registry = SkillRegistry(self.skills_dir)
        self.assertIn("reload_test", registry.documents)
        # 修改内容
        self._make_skill("reload_test", "After", "new content")
        registry.reload()
        self.assertEqual(registry.documents["reload_test"].body.strip(), "new content")


if __name__ == "__main__":
    unittest.main()
