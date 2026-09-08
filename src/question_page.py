"""Single composer and explicit retrieve/consent/answer interaction."""
import html
import json

import streamlit as st
from answer_service import generate_answer
from app_store import index_dirty, save_history, feedback


def reset_question(question=""):
    st.session_state.question_input = question
    st.session_state.allow_send = False
    for key in ("search", "answer", "history_id", "generation_error"):
        st.session_state.pop(key, None)


def render_question_page(root, resources, active_key, model, navigate):
    if index_dirty(root):
        st.warning("资料有更新，请先更新索引，再开始问答。")
        st.button("前往资料管理更新索引", on_click=navigate, args=("资料管理",))
        return
    questions_path = root / "_staging/20260908_网页模拟题/questions.json"
    questions = json.loads(questions_path.read_text(encoding="utf-8")) if questions_path.exists() else []
    with st.container(border=True):
        st.subheader("你想了解什么？")
        with st.form("search_form"):
            query = st.text_area("问题", key="question_input", label_visibility="collapsed",
                                 placeholder="直接输入问题，或从下方示例填入后修改…", max_chars=1000, height=100)
            submit, clear = st.columns([4, 1])
            submitted = submit.form_submit_button("查找资料", type="primary", width="stretch")
            clear.form_submit_button("新问题", on_click=reset_question, width="stretch")
        if "search" not in st.session_state:
            with st.expander("试试示例题 · 点击填入上方问题框"):
                st.caption("仅填入，不会自动检索或发送资料。示例题为未标注答案的 AI 草稿。")
                columns = st.columns(2)
                for i, item in enumerate(questions):
                    columns[i % 2].button(item["question"], key=f"example_{i}", width="stretch",
                                          on_click=reset_question, args=(item["question"],))
        with st.expander("高级选项"):
            split = st.checkbox("用 DeepSeek 拆分复杂问题", key="split_question")
            st.caption("默认关闭。开启后，查找资料时会发送问题与产品名；资料正文仍需另行确认。")
    if submitted:
        st.session_state.allow_send = False
        for key in ("answer", "search", "history_id", "generation_error"):
            st.session_state.pop(key, None)
        query = query.strip()
        if not query:
            st.warning("先写下一个问题，或点击示例题填入。")
        elif split and not active_key:
            st.warning("问题拆分需要 API。请先配置，或在高级选项关闭拆分。")
            st.button("去配置 API", on_click=navigate, args=("系统设置",))
        else:
            try:
                with st.status("正在查找本机资料…", expanded=True) as status:
                    st.write("首次加载模型可能较慢，请稍候。")
                    hybrid, lock = resources()
                    with lock:
                        if split:
                            from deepseek_decomposition import DeepSeekDecomposer
                            from decomposed_hybrid_eval import DecomposedHybridRetriever
                            retriever = DecomposedHybridRetriever(root, hybrid=hybrid, decomposer=DeepSeekDecomposer(
                                api_key=active_key, model=model, base_url="https://api.deepseek.com"))
                            result = retriever.search(query, "fde-core", 5)
                        else:
                            result = hybrid.search(query, "fde-core", 5)
                    st.session_state.search = result
                    st.session_state.history_id = save_history(root, query, result["results"])
                    status.update(label=f"资料查找完成 · {len(result['results'])} 条来源", state="complete", expanded=False)
            except Exception:
                st.error("检索未完成。请关闭同时运行的命令行检索后再试；若仍失败，请到资料管理检查索引。问题已保留。")

    if "search" not in st.session_state:
        st.caption("使用步骤：输入问题 → 查找资料 → 确认发送片段 → 查看最终回答。检索默认在本机完成。")
        return
    result = st.session_state.search
    evidence = result["results"]
    if not evidence:
        st.info("没有找到相关的可访问资料，暂不生成答案。试着补充产品名，或上传相关资料。")
        st.button("添加相关资料", on_click=navigate, args=("资料管理",))
        return

    answer_column, evidence_column = st.columns([7, 3], gap="large")
    with answer_column:
        # This placeholder always renders above controls, even after a generation click.
        final_area = st.container()
        with final_area:
            if "answer" not in st.session_state:
                st.subheader("资料已就绪，下一步生成回答")
                st.write("本次问题：" + result["query"])
        if "answer" not in st.session_state:
            if not active_key:
                st.info("资料已找到。请先配置 API，回来后可以继续，不用重新检索。")
                st.button("前往系统设置", on_click=navigate, args=("系统设置",))
            allowed = st.checkbox("允许将右侧最多 5 个脱敏片段发送给 DeepSeek，用于本次回答", key="allow_send")
            st.caption("每个片段最多 1600 字；仅在你点击生成后发送。")
            if st.button("生成最终回答", type="primary", disabled=not (active_key and allowed), width="stretch"):
                try:
                    with st.spinner("正在根据资料生成最终回答…"):
                        st.session_state.answer = generate_answer(result["query"], evidence, active_key, model, allow_send=allowed)
                    answer, usage, seconds = st.session_state.answer
                    st.session_state.history_id = save_history(root, result["query"], evidence, answer, usage, seconds)
                    st.session_state.pop("generation_error", None)
                    st.rerun()
                except ValueError as exc:
                    st.session_state.generation_error = str(exc)
            if st.session_state.get("generation_error"):
                st.error(st.session_state.generation_error + " 资料仍然保留，可再次点击生成重试。")
        else:
            answer, usage, seconds = st.session_state.answer
            with final_area:
                with st.container(border=True, key="final_answer"):
                    st.subheader("最终回答" if not answer["refused"] else "当前资料不足以回答")
                    st.caption("针对问题：" + result["query"])
                    if answer["refused"]:
                        st.warning(answer["message"])
                    else:
                        for claim in answer["claims"]:
                            text = html.escape(claim["text"])
                            refs = " ".join(f"[{i}]" for i in claim["citations"])
                            st.html(f'<p class="answer-claim">{text} <span class="answer-citations">{refs}</span></p>')
                    st.caption("AI 根据检索片段生成；引用编号对应右侧来源，重要结论请核对原文。")
            body = answer["message"] if answer["refused"] else "\n\n".join(
                c["text"] + " " + " ".join(f"[{i}]" for i in c["citations"]) for c in answer["claims"])
            source_text = "\n".join(f"[{i}] {x['source_file']} · {x['locator']}" for i, x in enumerate(evidence, 1))
            st.download_button("下载回答与来源", f"# {result['query']}\n\n{body}\n\n## 参考来源\n{source_text}",
                               "知识库回答.md", "text/markdown", width="stretch")
            with st.expander("评价本次回答"):
                rating = st.radio("回答质量", ["正确且证据充分", "答案有误", "引用不充分", "应该拒答"],
                                  key="quick_rating_" + st.session_state.history_id)
                if st.button("提交评价"):
                    feedback(root, st.session_state.history_id, rating, "")
                    st.success("已保存，可在问答历史中补充备注。")
            st.caption(f"耗时 {seconds} 秒 · {usage.get('total_tokens', '未知')} tokens · 已保存到问答历史")
    with evidence_column:
        st.subheader(f"参考来源 · {len(evidence)}")
        st.caption("展开核对原文，不必离开当前回答。")
        for i, item in enumerate(evidence, 1):
            with st.expander(f"[{i}] {item['source_file']}"):
                st.caption(item["section"] + " · " + item["locator"])
                st.text(item["text"][:1600])
        if result.get("decomposition"):
            with st.expander("查看问题拆分过程"):
                d = result["decomposition"]
                st.caption(f"{d['status']} · {d['latency_ms']/1000:.2f} 秒")
                for q in d["subqueries"]:
                    st.write(q)
