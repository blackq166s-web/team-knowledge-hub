import json
import sys
import threading
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from answer_service import connection_test
from app_store import initialize_snapshot, histories, feedback, read_json, write_json
from sample_questions import ensure_questions
from secure_credentials import load_key, save_key, delete_key
from ui_theme import apply_theme

st.set_page_config(page_title="团队知识库", layout="wide", initial_sidebar_state="expanded")
settings_path = ROOT / "data/app/settings.json"
settings = read_json(settings_path, {})
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = settings.get("theme") == "dark"
if st.session_state.pop("clear_key", False):
    st.session_state["api_key"] = ""
credential_error = ""
try:
    active_key = load_key(ROOT)
except ValueError as exc:
    active_key = ""
    credential_error = str(exc)
model = settings.get("model", "deepseek-v4-flash")
initialize_snapshot(ROOT)
ensure_questions(ROOT)


def remember_theme():
    current = read_json(settings_path, {})
    current["theme"] = "dark" if st.session_state.dark_mode else "light"
    write_json(settings_path, current)


def navigate(page):
    st.session_state.nav = page


apply_theme(st.session_state.dark_mode)


@st.cache_resource
def resources():
    from hybrid_baseline import HybridRetriever
    return HybridRetriever(ROOT), threading.Lock()


with st.sidebar:
    st.title("团队知识库")
    st.caption("TEAM KNOWLEDGE HUB · 本机初版")
    page = st.radio("功能入口", ["知识问答", "资料管理", "问答历史", "模拟题库", "系统设置"], key="nav")
    st.divider()
    st.toggle("黑夜模式", key="dark_mode", on_change=remember_theme)
    st.caption("DeepSeek · 已配置" if active_key else "DeepSeek · 未配置")
    st.caption("本机加密保存；连接状态请在设置中测试。")
    st.caption("本机试用 · 暂无团队登录")
heading, upload = st.columns([5, 1])
with heading:
    st.title(page)
    st.caption("让团队资料成为有来源、可核对的回答")
with upload:
    st.button("上传 / 管理资料", on_click=navigate, args=("资料管理",), width="stretch")
if credential_error:
    st.warning(credential_error)
if page == "系统设置":
    st.subheader("DeepSeek 接入")
    st.info("保存一次后，刷新或重启程序都会自动读取。密钥只在这台电脑的当前 Windows 用户下解密，不会上传 Git。")
    st.caption("服务地址固定为 https://api.deepseek.com。换电脑或换 Windows 用户，需要重新输入密钥。")
    st.text_input("API Key", type="password", key="api_key", placeholder="输入新密钥；留空保留已保存密钥")
    chosen_model = st.text_input("模型名称", value=model)
    st.caption("仅输入不会保存；点击下面的保存按钮后，才会加密写入本机。请使用重新生成的密钥。")
    save_col, test_col, clear_col = st.columns(3)
    with save_col:
        if st.button("保存设置", type="primary", width="stretch"):
            try:
                if st.session_state.api_key.strip():
                    save_key(ROOT, st.session_state.api_key)
                current = read_json(settings_path, {})
                current["model"] = chosen_model.strip() or model
                write_json(settings_path, current)
                st.session_state.clear_key = True
                st.session_state.settings_saved = True
                st.rerun()
            except (ValueError, OSError):
                st.error("保存失败，请检查密钥和本机目录权限。")
    with test_col:
        if st.button("测试 API 连接", width="stretch"):
            try:
                with st.spinner("正在测试连接…"):
                    usage, seconds = connection_test(st.session_state.api_key.strip() or active_key, chosen_model)
                st.success(f"本次连接通过 · {seconds} 秒 · {usage.get('total_tokens', '未知')} tokens")
                st.caption("测试新输入的密钥不会自动保存，请点击保存设置。")
            except ValueError as exc:
                st.error(str(exc))
    with clear_col:
        if st.button("清除密钥", width="stretch"):
            delete_key(ROOT)
            st.session_state.clear_key = True
            st.session_state.settings_saved = False
            st.session_state.key_deleted = True
            st.rerun()
    if st.session_state.pop("settings_saved", False):
        st.success("设置已保存；输入框已清空，已保存的密钥会在后台自动使用。")
    if st.session_state.pop("key_deleted", False):
        st.success("本机保存的密钥已删除；此操作无法恢复，可重新输入。")
    st.divider()
    st.subheader("外观与数据")
    st.write("左侧黑夜模式会记住你的选择。资料、历史和设置只存本机，Git 只同步程序代码。")
    st.warning("这是本机初版，不要直接开放公网。加密保存不能防止当前 Windows 用户下的恶意程序读取密钥。")
    st.stop()
if page == "资料管理":
    from document_manager import render_documents
    render_documents(ROOT, resources)
    st.stop()
if page == "问答历史":
    st.subheader("问答历史与反馈")
    st.caption("记录只保存在本机 data/app；保存问题、答案和来源位置，不保存 API Key 或检索全文。")
    records = histories(ROOT)
    keyword = st.text_input("搜索历史问题")
    records = [r for r in records if keyword.lower() in r["question"].lower()]
    if not records:
        st.info("还没有记录。先去知识问答查一道题。")
    else:
        selected = st.selectbox("历史记录", records, format_func=lambda r:r["time"][:19]+" · "+r["question"])
        st.write(selected["question"])
        answer = selected.get("answer")
        if answer:
            if answer["refused"]:
                st.warning(answer["message"])
            else:
                for claim in answer["claims"]:
                    st.write(claim["text"]+" "+" ".join(f"[{i}]" for i in claim["citations"]))
        else:
            st.caption("此条记录只进行了检索")
        st.dataframe(selected["sources"], hide_index=True, width="stretch")
        rating = st.radio("本次质量", ["未评价","正确且证据充分","答案有误","引用不充分","应该拒答"], key="rating_"+selected["id"])
        note = st.text_area("备注", value=selected.get("note",""), key="note_"+selected["id"], max_chars=2000)
        st.caption("已保存评价："+selected.get("feedback","未评价"))
        if st.button("保存反馈"):
            feedback(ROOT, selected["id"], rating, note)
            st.success("反馈已保存")
        st.download_button("导出历史记录", json.dumps(records, ensure_ascii=False, indent=2), "kb-history.json", "application/json")
    st.stop()
if page == "模拟题库":
    st.subheader("20 道模拟新题")
    st.caption("AI 模拟草稿，尚未标注标准证据；用于试用，不是已完成的盲测成绩。")
    draft = ROOT / "_staging" / "20260908_网页模拟题" / "questions.json"
    if draft.exists():
        text = draft.read_text(encoding="utf-8")
        st.dataframe(json.loads(text), hide_index=True, width="stretch")
        st.download_button("下载模拟题", text, "questions.json", "application/json")
    st.markdown("1. 打开资料管理，确认资料已入库。\n2. 在系统设置中保存新的 API Key 并测试连接。\n3. 回到知识问答，选题并查找资料。\n4. 核对片段，确认发送后生成答案。\n5. 记录答案是否正确、引用是否支持结论。")
    st.code(".\\scripts\\kb.ps1 web", language="powershell")
    st.markdown("**初版范围**：本机管理、文本检索与在线问答。支持 DOCX 正文/表格和文字型 PDF；扫描 OCR、图片语义、旧版 DOC、真实团队登录暂不支持。")
    st.markdown("**资料更新**：上传和修改后点击更新索引，归档也需更新索引。更新期间不能并行运行命令行检索。")
    st.markdown("**迁移**：Git 只带代码。另行安全复制 data、_staging/uploads、模拟题草稿；可复制 .cache 节省下载。不要复制 .venv，换电脑重新 setup。")
    st.stop()
from question_page import render_question_page
render_question_page(ROOT, resources, active_key, model, navigate)
