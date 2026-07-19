"""
命令行主入口：协调「评论爬取 → 情感分析 → CSV 导出」完整流程

使用示例：
    python src/main.py --url "https://www.xiaohongshu.com/explore/123abc" --output data/result.csv
"""
import argparse
import logging
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

# 将项目根目录加入路径，保证 src 下模块可被导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from crawler import XHSCrawler
from sentiment_analyzer import SentimentAnalyzer
from utils import load_config, save_to_csv, setup_logging


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="小红书笔记评论爬取 + 中文情感三分类分析"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="小红书笔记分享链接（支持 /explore/、/discovery/item/ 等形态）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出 CSV 文件路径，默认保存到 data/comments_<note_id>_<timestamp>.csv",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="配置文件路径，默认 config.yaml",
    )
    return parser.parse_args()


def build_output_path(url: str, output_arg: Optional[str], output_cfg: dict) -> str:
    """根据命令行参数与配置确定输出文件路径"""
    if output_arg:
        return output_arg

    default_dir = output_cfg.get("default_dir", "./data")
    crawler_cfg = {"note_base_url": "https://www.xiaohongshu.com/explore/{note_id}"}
    note_id = XHSCrawler({"crawler": crawler_cfg}).extract_note_id(url)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(default_dir, f"comments_{note_id}_{timestamp}.csv")


def main() -> None:
    args = parse_args()

    # 加载配置并初始化日志
    config = load_config(args.config)
    setup_logging(config.get("logging", {}).get("level", "INFO"))

    output_cfg = config.get("output", {})
    encoding = output_cfg.get("csv_encoding", "utf-8-sig")
    output_path = build_output_path(args.url, args.output, output_cfg)

    # 1. 爬取评论
    logging.info("开始采集笔记评论：%s", args.url)
    crawler = XHSCrawler(config)
    comments = crawler.fetch_comments(args.url)
    if not comments:
        logging.warning("未采集到任何评论，请检查链接有效性、登录态或页面是否触发验证")
        return

    logging.info("评论采集完成，共 %d 条，开始进行情感分析...", len(comments))

    # 2. 情感分析
    analyzer = SentimentAnalyzer(config)
    enriched = []
    for c in comments:
        result = analyzer.analyze(c["content"])
        c.update(result)
        enriched.append(c)

    # 3. 导出 CSV
    save_to_csv(enriched, output_path, encoding=encoding)

    # 4. 控制台汇总
    counter = Counter(r["sentiment"] for r in enriched)
    logging.info("情感分布统计：%s", dict(counter))
    logging.info("任务完成，输出文件：%s", output_path)


if __name__ == "__main__":
    main()
