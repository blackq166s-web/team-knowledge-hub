import json
import sys
import threading
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from answer_service import connection_test, generate_answer
from app_store import initialize_snapshot, index_dirty, save_history, histories, feedback, read_json, write_json
from sample_questions import ensure_questions

st.set_page_config(page_title="团队知识库", layout="wide")
if st.session_state.pop("clear_key", False):
    st.session_state["api_key"] = ""
    st.session_state["saved_key"] = ""
initialize_snapshot(ROOT)
ensure_questions(ROOT)


def remember_key():
    st.session_state["saved_key"] = st.session_state.api_key


@st.cache_resource
def resources():
    from hybrid_baseline import HybridRetriever
    return HybridRetriever(ROOT), threading.Lock()


st.title("团队知识库")
st.caption("v0.1 · 本机个人管理版 · 资料、问答、历史与反馈")
page = st.radio("功能入口", ["知识问答", "资料管理", "问答历史", "模拟题与使用说明"], horizontal=True)
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
if page == "模拟题与使用说明":
    st.subheader("20 道模拟新题")
    st.caption("AI 模拟草稿，尚未标注标准证据；用于试用，不是已完成的盲测成绩。")
    draft = ROOT / "_staging" / "20260908_网页模拟题" / "questions.json"
    if draft.exists():
        text = draft.read_text(encoding="utf-8")
        st.dataframe(json.loads(text), hide_index=True, width="stretch")
        st.download_button("下载模拟题", text, "questions.json", "application/json")
    st.markdown("1. 打开资料管理，确认资料已入库。\n2. 回到知识问答，选题并查找资料。\n3. 输入新的 API Key 并测试连接。\n4. 核对片段，确认发送后生成答案。\n5. 记录答案是否正确、引用是否支持结论。")
    st.code(".\\scripts\\kb.ps1 web", language="powershell")
    st.markdown("**初版范围**：本机管理、文本检索与在线问答。支持 DOCX 正文/表格和文字型 PDF；扫描 OCR、图片语义、旧版 DOC、真实团队登录暂不支持。")
    st.markdown("**资料更新**：上传和修改后点击更新索引，归档也需更新索引。更新期间不能并行运行命令行检索。")
    st.markdown("**迁移**：Git 只带代码。另行安全复制 data、_staging/uploads、模拟题草稿；可复制 .cache 节省下载。不要复制 .venv，换电脑重新 setup。")
    st.stop()
with st.sidebar:
    st.subheader("DeepSeek API")
    if "api_key" not in st.session_state:
        st.session_state.api_key = st.session_state.get("saved_key", "")
    st.text_input("API Key", type="password", key="api_key", on_change=remember_key, help="仅在当前会话使用，不写入项目文件。请使用新生成的密钥。")
    settings = read_json(ROOT/"data/app/settings.json", {})
    model = st.text_input("模型名称", value=settings.get("model","deepseek-v4-flash"))
    if st.button("保存模型设置"):
        write_json(ROOT/"data/app/settings.json", {"model":model.strip() or "deepseek-v4-flash"})
        st.success("模型设置已保存，API Key 不会保存到文件")
    if st.button("清除密钥"):
        # A callback-style reset on the next run avoids modifying an active widget.
        st.session_state["clear_key"] = True
        st.rerun()
    if st.button("测试 API 连接"):
        try:
            with st.spinner("测试连接…"):
                usage, seconds = connection_test(st.session_state.api_key, model)
            st.success(f"连接成功 · {seconds} 秒 · {usage.get('total_tokens', '未知')} tokens")
        except ValueError as exc:
            st.error(str(exc))
    split = st.checkbox("用 DeepSeek 拆分复杂问题", value=False)
    st.caption("拆分仅发送问题与产品名。生成答案另需确认发送资料片段。")
    st.info("仅供本机试用。当前固定使用模拟 fde-core 用户，尚未接入团队登录。")

if index_dirty(ROOT):
    st.warning("资料已变更或索引未建立。请前往资料管理更新索引，再开始问答。")
    st.stop()

questions_path = ROOT / "_staging" / "20260908_网页模拟题" / "questions.json"
questions = json.loads(questions_path.read_text(encoding="utf-8")) if questions_path.exists() else []
st.selectbox("模拟新题（也可以自行输入）", ["自行输入"] + [q["question"] for q in questions], key="sample")
with st.form("search_form"):
    query = st.text_area("你的问题", value="", placeholder="留空可使用上方模拟题", max_chars=1000)
    submitted = st.form_submit_button("查找资料", type="primary")
if submitted:
    query = query.strip() or (st.session_state.sample if st.session_state.sample != "自行输入" else "")
    if not query:
        st.warning("请输入问题或选择一道模拟题。")
    elif split and not st.session_state.api_key.strip():
        st.warning("请先输入 API Key，或取消问题拆分。")
    else:
        st.session_state["allow_send"] = False
        st.session_state.pop("answer", None)
        st.session_state.pop("search", None)
        try:
            with st.spinner("加载模型并检索资料，首次运行稍慢…"):
                hybrid, lock = resources()
                with lock:
                    if split:
                        from deepseek_decomposition import DeepSeekDecomposer
                        from decomposed_hybrid_eval import DecomposedHybridRetriever
                        retriever = DecomposedHybridRetriever(ROOT, hybrid=hybrid, decomposer=DeepSeekDecomposer(
                            api_key=st.session_state.api_key, model=model, base_url="https://api.deepseek.com"))
                        result = retriever.search(query, "fde-core", 5)
                    else:
                        result = hybrid.search(query, "fde-core", 5)
            st.session_state.search = result
            st.session_state.history_id = save_history(ROOT, query, result["results"])
        except Exception:
            st.error("检索未完成。请确认本机索引已建立，并关闭占用 Qdrant 的命令行评测后重试。")

if "search" in st.session_state:
    result = st.session_state.search
    st.subheader("找到的资料")
    st.write(result["query"])
    if result.get("decomposition"):
        d = result["decomposition"]
        st.caption(f"问题拆分状态：{d['status']} · {d['latency_ms']/1000:.2f} 秒")
        for q in d["subqueries"]:
            st.write(q)
    evidence = result["results"]
    for i, item in enumerate(evidence, 1):
        with st.expander(f"[{i}] {item['source_file']} · {item['section']}"):
            st.caption(item["locator"])
            st.text(item["text"][:1600])
            if len(item["text"]) > 1600:
                st.caption("此处展示与发送前 1600 字；完整内容可从资料管理查看。")
    if not evidence:
        st.info("未找到可访问的资料。")
    allowed = st.checkbox("允许将上方最多 5 个脱敏片段发送给 DeepSeek，用于本次回答", key="allow_send")
    if st.button("根据资料生成答案", disabled=not evidence):
        st.session_state.pop("answer", None)
        try:
            with st.spinner("DeepSeek 正在根据证据回答…"):
                st.session_state.answer = generate_answer(result["query"], evidence, st.session_state.api_key, model, allow_send=allowed)
                answer, usage, seconds = st.session_state.answer
                st.session_state.history_id = save_history(ROOT, result["query"], evidence, answer, usage, seconds)
        except ValueError as exc:
            st.error(str(exc))
    if "answer" in st.session_state:
        answer, usage, seconds = st.session_state.answer
        st.subheader("回答")
        if answer["refused"]:
            st.warning(answer["message"])
        else:
            for claim in answer["claims"]:
                st.write(claim["text"] + " " + " ".join(f"[{i}]" for i in claim["citations"]))
        st.caption(f"生成耗时 {seconds} 秒 · {usage.get('total_tokens', '未知')} tokens；编号对应上方原文，引用存在不等于语义正确，请核对。")
        st.download_button("下载本次结果", json.dumps({"question":result["query"], "answer":answer,
            "sources":[{"id":i,"file":x["source_file"],"locator":x["locator"]} for i,x in enumerate(evidence,1)],
            "usage":usage}, ensure_ascii=False, indent=2), "kb-answer.json", "application/json")
with st.expander("怎么使用 / 如何换电脑"):
    st.write("1. 先选择模拟题，点击查找资料；此步骤默认不需要 API。")
    st.write("2. 在左侧输入新的 DeepSeek API Key，点击测试 API 连接。")
    st.write("3. 核对找到的片段，勾选发送许可，再点击根据资料生成答案。")
    st.write("4. 如需复杂问题拆分，勾选左侧选项并重新检索。")
    st.code(".\\scripts\\kb.ps1 web", language="powershell")
    st.write("换电脑：克隆 Git，运行 setup，安全复制本机资料并重建索引。模型和密钥不随 Git 迁移。")
