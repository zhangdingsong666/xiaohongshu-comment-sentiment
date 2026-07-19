"""
Web 端专用辅助函数：生成 Excel 文件与 Plotly 饼状图
"""
import io
from typing import Optional

import pandas as pd
import plotly.express as px


# 情感标签 → 颜色映射（与 UI 保持一致）
SENTIMENT_COLORS = {
    "正面": "#2ecc71",
    "中性": "#95a5a6",
    "负面": "#e74c3c",
}


def make_pie_chart(df: pd.DataFrame, title: str = "情感分布") -> Optional[px.Figure]:
    """
    根据 DataFrame 中的 sentiment 列生成情感分布饼状图。

    Args:
        df: 包含 sentiment 列的 DataFrame
        title: 图表标题

    Returns:
        Plotly Figure 对象；数据为空时返回 None
    """
    if df.empty or "sentiment" not in df.columns:
        return None

    counts = df["sentiment"].value_counts().reset_index()
    counts.columns = ["sentiment", "count"]

    # 保证三种情感都有颜色，缺失标签使用默认颜色
    color_map = {
        label: SENTIMENT_COLORS.get(label, "#3498db")
        for label in counts["sentiment"].unique()
    }

    fig = px.pie(
        counts,
        names="sentiment",
        values="count",
        title=title,
        color="sentiment",
        color_discrete_map=color_map,
    )
    fig.update_traces(
        textposition="inside",
        textinfo="percent+label",
        hole=0.35,  # 环形图，更美观
    )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        margin=dict(t=60, b=60, l=20, r=20),
    )
    return fig


def generate_excel(df: pd.DataFrame, sheet_name: str = "评论情感分析") -> bytes:
    """
    将 DataFrame 导出为 Excel 字节流，供 Streamlit 下载按钮使用。

    Args:
        df: 待导出的数据
        sheet_name: Excel 工作表名称

    Returns:
        Excel 文件的字节内容
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)

        # 自动调整列宽，提升 Excel 可读性
        worksheet = writer.sheets[sheet_name]
        for column_cells in worksheet.iter_cols(min_row=1, max_row=1):
            header_cell = column_cells[0]
            col_letter = header_cell.column_letter
            max_length = len(str(header_cell.value)) if header_cell.value else 0
            for cell in worksheet[col_letter]:
                try:
                    cell_length = len(str(cell.value))
                    if cell_length > max_length:
                        max_length = cell_length
                except Exception:
                    pass
            # 限制最大宽度，避免超长内容导致列过宽
            worksheet.column_dimensions[col_letter].width = min(max_length + 2, 60)

    return buffer.getvalue()
