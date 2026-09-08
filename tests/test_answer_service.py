import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from answer_service import generate_answer
from document_manager import save_upload, promote


class AnswerTests(unittest.TestCase):
    def evidence(self):
        return [{"source_file":"demo.md","locator":"L1","text":"演示服务每周一维护。","acl":"fde-core"}]

    def transport(self, payload):
        def reply(request):
            body = json.loads(request.content)
            assert "演示服务" in body["messages"][1]["content"]
            return httpx.Response(200, json={"choices":[{"finish_reason":"stop","message":{"content":json.dumps(payload)}}],"usage":{"total_tokens":20}})
        return httpx.MockTransport(reply)

    def test_requires_consent_before_network(self):
        with self.assertRaisesRegex(ValueError, "确认"):
            generate_answer("何时维护", self.evidence(), "test", "model")

    def test_citation_and_usage(self):
        payload = {"refused":False,"claims":[{"text":"周一维护","citations":[1]}]}
        answer, usage, _ = generate_answer("何时维护", self.evidence(), "test", "model", allow_send=True, transport=self.transport(payload))
        self.assertEqual(answer["claims"], payload["claims"])
        self.assertEqual(usage["total_tokens"], 20)

    def test_rejects_invented_source(self):
        payload = {"refused":False,"claims":[{"text":"周一维护","citations":[9]}]}
        with self.assertRaisesRegex(ValueError, "无效引用"):
            generate_answer("何时维护", self.evidence(), "test", "model", allow_send=True, transport=self.transport(payload))

    def test_refusal(self):
        payload = {"refused":True,"message":"证据不足"}
        answer, _, _ = generate_answer("谁负责", self.evidence(), "test", "model", allow_send=True, transport=self.transport(payload))
        self.assertTrue(answer["refused"])

    def test_no_access(self):
        evidence = self.evidence()
        evidence[0]["acl"] = "private"
        with self.assertRaisesRegex(ValueError, "权限"):
            generate_answer("何时维护", evidence, "test", "model", allow_send=True)

    def test_upload_and_promote(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = save_upload(root, "../../demo.txt", "这是演示资料".encode())
            self.assertEqual(path.parent, root / "_staging" / "uploads")
            target = promote(root, path, "团队通用", "团队说明")
            self.assertIn("acl: fde-core", target.read_text(encoding="utf-8"))
            self.assertIn("## 上传正文", target.read_text(encoding="utf-8"))
            with self.assertRaises(ValueError):
                promote(root, path, "团队通用", "团队说明")


if __name__ == '__main__':
    unittest.main()
