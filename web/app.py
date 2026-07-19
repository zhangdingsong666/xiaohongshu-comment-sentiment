"""
Streamlit Web 应用：小红书笔记评论爬取 + 情感分析

功能：
- 粘贴小红书笔记链接
- 自动爬取评论（含楼中楼）
- 进行中文情感三分类
- 展示数据表格、情感分布饼状图
- 一键下载 Excel 结果

启动方式：
    streamlit run web/app.py
"""
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# 将项目根目录下的 src 加入 Python 路径，复用现有模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from crawler import XHSCrawler
from sentiment_analyzer import SentimentAnalyzer
from utils import load_config

from helpers import generate_excel, make_pie_chart


# 页面基础配置
st.set_page_config(
    page_title="小红书评论情感分析",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_session_state() -> None:
    """初始化会话状态，避免 Streamlit 重跑时丢失结果"""
    defaults = {
        "df": None,
        "analyzed": False,
        "error": None,
        "url": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def extract_note_id_for_filename(url: str) -> str:
    """从 URL 提取 note_id 作为 Excel 文件名的一部分"""
    try:
        return XHSCrawler({"crawler": {}}).extract_note_id(url)
    except Exception:
        return "result"


def main() -> None:
    init_session_state()

    st.title("📊 小红书笔记评论情感分析")
    st.markdown(
        "输入小红书笔记链接，自动爬取评论、分析情感，并生成 **Excel 表格** 与 **饼状图**。"
    )

    # 加载配置文件
    config_path = PROJECT_ROOT / "config.yaml"
    try:
        config = load_config(str(config_path))
    except FileNotFoundError:
        st.error(
            "找不到 `config.yaml`。请先复制 `config.example.yaml` 为 `config.yaml` 后再启动。"
        )
        return

    crawler_cfg = config.setdefault("crawler", {})
    auth_path = crawler_cfg.get("auth_state_path", "./auth_state.json")

    # ------------------------------------------------------------------
    # 侧边栏设置
    # ------------------------------------------------------------------
    with st.sidebar:
        st.header("⚙️ 运行设置")

        max_comments = st.number_input(
            "最大采集评论数（0 = 不限制）",
            min_value=0,
            max_value=5000,
            value=crawler_cfg.get("max_comments", 0) or 0,
            step=10,
            help="限制采集数量可加快分析速度，0 表示采集全部可加载评论。",
        )

        # 首次登录建议关闭无头模式，方便扫码
        default_headless = True if os.path.exists(auth_path) else False
        headless = st.checkbox(
            "无头模式运行浏览器",
            value=default_headless,
            help="首次使用或登录态过期时，请取消勾选此选项以弹出浏览器扫码登录。",
        )

        st.markdown("---")
        st.markdown("**登录状态检测**")
        if os.path.exists(auth_path):
            st.success("✅ 已检测到登录态，将自动复用")
        else:
            st.warning("⚠️ 未检测到登录态")
            st.info(
                "请取消勾选「无头模式」，点击「开始分析」后会弹出浏览器，扫码登录即可。"
            )

        st.markdown("---")
        st.markdown("**使用说明**")
        st.markdown(
            """
            1. 粘贴小红书笔记链接
            2. 按需调整最大采集数
            3. 点击「开始分析」
            4. 等待爬取与分析完成
            5. 查看表格、饼图，下载 Excel
            """
        )

    # ------------------------------------------------------------------
    # 主界面输入
    # ------------------------------------------------------------------
    url = st.text_input(
        "🔗 小红书笔记链接",
        value=st.session_state.get("url", ""),
        placeholder="https://www.xiaohongshu.com/explore/你的笔记ID",
    )
    st.session_state["url"] = url

    start_col, _ = st.columns([1, 3])
    with start_col:
        start = st.button("🚀 开始分析", use_container_width=True)

    # ------------------------------------------------------------------
    # 执行分析
    # ------------------------------------------------------------------
    if start:
        if not url or not url.strip():
            st.error("请先输入小红书笔记链接")
            return

        # 根据页面设置覆盖配置
        crawler_cfg["max_comments"] = int(max_comments)
        crawler_cfg["headless"] = bool(headless)

        # 重置结果
        st.session_state.df = None
        st.session_state.error = None
        st.session_state.analyzed = False

        # 1) 爬取评论
        with st.status("正在爬取评论，请稍候...", expanded=True) as status:
            try:
                crawler = XHSCrawler(config)
                comments = crawler.fetch_comments(url)
                status.update(
                    label=f"✅ 评论爬取完成，共 {len(comments)} 条",
                    state="complete",
                )
            except Exception as exc:
                status.update(label="❌ 爬取失败", state="error")
                st.session_state.error = str(exc)
                st.error(f"爬取失败：{exc}")
                st.info(
                    "常见原因：链接无效、登录态过期、触发平台风控。"
                    "请检查链接，或删除 auth_state.json 后重新扫码登录。"
                )
                return

        # 2) 情感分析
        with st.status("正在进行情感分析...", expanded=True) as status:
            analyzer = SentimentAnalyzer(config)
            enriched = []
            total = len(comments)
            progress_bar = st.progress(0, text="情感分析进度：0%")

            for i, comment in enumerate(comments, start=1):
                result = analyzer.analyze(comment["content"])
                comment.update(result)
                enriched.append(comment)
                pct = int(min(i / total, 1.0) * 100)
                progress_bar.progress(min(i / total, 1.0), text=f"情感分析进度：{pct}%")

            progress_bar.empty()
            status.update(label="✅ 情感分析完成", state="complete")

        st.session_state.df = pd.DataFrame(enriched)
        st.session_state.analyzed = True
        st.rerun()

    # ------------------------------------------------------------------
    # 结果展示
    # ------------------------------------------------------------------
    if st.session_state.error:
        st.error(f"上次运行出错：{st.session_state.error}")

    if st.session_state.analyzed and st.session_state.df is not None:
        df: pd.DataFrame = st.session_state.df

        st.divider()
        st.subheader("📈 统计概览")
        total = len(df)
        pos = int((df["sentiment"] == "正面").sum())
        neu = int((df["sentiment"] == "中性").sum())
        neg = int((df["sentiment"] == "负面").sum())

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("评论总数", total)
        c2.metric("😊 正面", pos)
        c3.metric("😐 中性", neu)
        c4.metric("😠 负面", neg)

        st.divider()
        st.subheader("🥧 情感分布饼状图")
        fig = make_pie_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无有效情感数据，无法绘制饼状图。")

        st.divider()
        st.subheader("📋 评论数据详情")
        st.dataframe(df, use_container_width=True, height=500)

        st.divider()
        st.subheader("⬇️ 导出 Excel")
        excel_bytes = generate_excel(df)
        note_id = extract_note_id_for_filename(url)
        filename = f"xhs_comments_{note_id}.xlsx"
        st.download_button(
            label="下载 Excel 表格",
            data=excel_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
