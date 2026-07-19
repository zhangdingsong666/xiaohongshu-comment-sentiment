"""
通用工具函数：配置读取、日志、随机延时、CSV 导出等
"""
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import yaml


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """读取 YAML 配置文件，若不存在则给出明确提示"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"配置文件不存在：{config_path}。请先执行：cp config.example.yaml {config_path}"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def setup_logging(level: str = "INFO") -> None:
    """初始化日志格式与级别"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def random_sleep(min_sec: float, max_sec: float) -> None:
    """在 [min_sec, max_sec] 之间随机休眠，模拟真实人工操作"""
    if min_sec > max_sec:
        min_sec, max_sec = max_sec, min_sec
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def ensure_dir(path: str) -> str:
    """确保目录存在，返回目录绝对路径"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return str(p.resolve())


def save_to_csv(
    records: List[Dict[str, Any]], output_path: str, encoding: str = "utf-8-sig"
) -> None:
    """将字典列表导出为 CSV"""
    if not records:
        logging.warning("没有数据可导出，跳过 CSV 写入")
        return
    df = pd.DataFrame(records)
    parent = os.path.dirname(output_path) or "."
    ensure_dir(parent)
    df.to_csv(output_path, index=False, encoding=encoding)
    logging.info("结果已导出：%s，共 %d 条记录", output_path, len(df))
