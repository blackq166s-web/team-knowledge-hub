import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

SOURCE = '''
from pathlib import Path
import threading
import streamlit as st
from question_page import render_question_page
class Retriever:
    def search(self, query, group, limit):
        return {"query": query, "results": [] if query == "empty" else [{
            "source_file":"test.md", "section":"test", "locator":"L1", "text":"test evidence"}]}
render_question_page(Path("unused-test-root"), lambda: (Retriever(), threading.Lock()), "fake-test-key", "test-model", lambda page: None)
'''


class QuestionFlowTests(unittest.TestCase):
    def test_retry_and_changed_question_consent(self):
        with patch("question_page.index_dirty", return_value=False), patch("question_page.save_history", return_value="a"*32), patch("question_page.generate_answer") as generate:
            app = AppTest.from_string(SOURCE).run()
            app.text_area(key="question_input").set_value("first question").run()
            next(b for b in app.button if b.label == "查找资料").click().run()
            self.assertTrue(next(b for b in app.button if b.label == "生成最终回答").disabled)
            generate.assert_not_called()
            app.checkbox(key="allow_send").check().run()
            generate.side_effect = ValueError("测试连接失败")
            next(b for b in app.button if b.label == "生成最终回答").click().run()
            self.assertTrue(app.error)
            self.assertIn("search", app.session_state)
            generate.side_effect = None
            generate.return_value = ({"refused": True, "message":"证据不足", "claims":[]}, {}, 0)
            next(b for b in app.button if b.label == "生成最终回答").click().run()
            self.assertTrue(any(h.value == "当前资料不足以回答" for h in app.subheader))
            app.text_area(key="question_input").set_value("changed question").run()
            next(b for b in app.button if b.label == "查找资料").click().run()
            self.assertNotIn("answer", app.session_state)
            self.assertFalse(app.checkbox(key="allow_send").value)
            self.assertEqual(app.session_state["search"]["query"], "changed question")
            app.text_area(key="question_input").set_value("empty").run()
            next(b for b in app.button if b.label == "查找资料").click().run()
            self.assertFalse(any(b.label == "生成最终回答" for b in app.button))
            self.assertFalse(app.exception)
