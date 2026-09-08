import sys
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
app = AppTest.from_file(str(root / "src" / "web_app.py"), default_timeout=90).run()
assert not app.exception, app.exception
next(b for b in app.button if b.label == "W001 的总功耗要求是多少？").click().run()
assert app.text_area(key="question_input").value == "W001 的总功耗要求是多少？"
assert not app.selectbox
next(b for b in app.button if b.label == "查找资料").click().run(timeout=90)
assert not app.exception, app.exception
assert "search" in app.session_state
assert len(app.session_state["search"]["results"]) > 0
assert not app.session_state["allow_send"]
assert next(b for b in app.button if b.label == "生成最终回答").disabled
app.checkbox(key="allow_send").check().run()
with patch("secure_credentials.load_key", return_value="test-only-value"), patch("answer_service.request_json", return_value=({"refused":False,"claims":[{"text":"自动化测试模拟响应，不是业务答案","citations":[1]}]}, {"total_tokens":20}, 0.01)):
    app.run()
    next(b for b in app.button if b.label == "生成最终回答").click().run()
assert not app.exception, app.exception
assert "answer" in app.session_state
assert app.session_state["answer"][1]["total_tokens"] == 20
assert any(h.value == "最终回答" for h in app.subheader)
next(b for b in app.button if b.label == "提交评价").click().run()
assert any("已保存" in s.value for s in app.success)
next(b for b in app.button if b.label == "新问题").click().run()
assert "answer" not in app.session_state and "search" not in app.session_state
assert app.text_area(key="question_input").value == ""
next(b for b in app.button if b.label == "查找资料").click().run()
assert any("先写下" in w.value for w in app.warning)
app.radio(key="nav").set_value("系统设置").run()
app.text_input(key="api_key").set_value("test-only-value").run()
with patch("secure_credentials.save_key") as save:
    next(b for b in app.button if b.label == "保存设置").click().run()
    save.assert_called_once_with(root, "test-only-value")
assert app.session_state["api_key"] == ""
with patch("secure_credentials.delete_key") as delete:
    next(b for b in app.button if b.label == "清除密钥").click().run()
    delete.assert_called_once_with(root)
assert app.session_state["api_key"] == ""
app.radio(key="nav").set_value("资料管理").run()
assert not app.exception, app.exception
assert len(app.dataframe) >= 1
app.radio(key="nav").set_value("模拟题库").run()
assert not app.exception, app.exception
app.radio(key="nav").set_value("问答历史").run()
assert not app.exception, app.exception
assert len(app.dataframe) >= 1
from app_store import read_json, write_json
settings_path = root / "data/app/settings.json"
original = read_json(settings_path, {})
try:
    app.toggle(key="dark_mode").set_value(True).run()
    assert read_json(settings_path, {})["theme"] == "dark"
    fresh = AppTest.from_file(str(root / "src/web_app.py"), default_timeout=90).run()
    assert fresh.toggle(key="dark_mode").value
    fresh.toggle(key="dark_mode").set_value(False).run()
    assert read_json(settings_path, {})["theme"] == "light"
    assert not fresh.exception
finally:
    write_json(settings_path, original)
print("PASS: real local retrieval, consent guard, MOCK generation/citations/usage, key clearing, documents page, 20-question page, persisted history")
