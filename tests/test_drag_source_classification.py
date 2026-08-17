import ast
import unittest
from pathlib import Path


class DragSourceClassificationTests(unittest.TestCase):
    def test_known_frontend_payload_sources_are_explicitly_classified(self):
        root = Path(__file__).resolve().parents[1] / "frontend"
        missing = []
        for path in root.rglob("*.py"):
            if "dragdrop" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name) or node.func.id != "DragPayload":
                    continue
                keywords = {keyword.arg for keyword in node.keywords}
                if "status" not in keywords or "provenance" not in keywords:
                    missing.append(f"{path.relative_to(root)}:{node.lineno}")

        self.assertEqual(missing, [], f"Sources sans classification explicite: {missing}")


if __name__ == "__main__":
    unittest.main()
