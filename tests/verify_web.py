import sys
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
app = AppTest.from_file(str(root / "src" / "web_app.py"), default_timeout=90).run()
assert not app.exception, app.exception
app.selectbox(key="sample").select("W001 的总功耗要求是多少？").run()
next(b for b in app.button if b.label == "查找资料").click().run(timeout=90)
assert not app.exception, app.exception
assert "search" in app.session_state
assert len(app.session_state["search"]["results"]) > 0
assert not app.session_state["allow_send"]
next(b for b in app.button if b.label == "根据资料生成答案").click().run()
assert any("确认" in e.value for e in app.error)
app.text_input(key="api_key").set_value("test-only-value").run()
app.checkbox(key="allow_send").check().run()
with patch("answer_service.request_json", return_value=({"refused":False,"claims":[{"text":"自动化测试模拟响应，不是业务答案","citations":[1]}]}, {"total_tokens":20}, 0.01)):
    next(b for b in app.button if b.label == "根据资料生成答案").click().run()
assert not app.exception, app.exception
assert "answer" in app.session_state
assert app.session_state["answer"][1]["total_tokens"] == 20
next(b for b in app.button if b.label == "清除密钥").click().run()
assert app.session_state["api_key"] == ""
app.radio[0].set_value("资料管理").run()
assert not app.exception, app.exception
assert len(app.dataframe) >= 1
app.radio[0].set_value("模拟题与使用说明").run()
assert not app.exception, app.exception
app.radio[0].set_value("问答历史").run()
assert not app.exception, app.exception
assert len(app.dataframe) >= 1
print("PASS: real local retrieval, consent guard, MOCK generation/citations/usage, key clearing, documents page, 20-question page, persisted history")
