"""
中文情感三分类分析模块

默认使用 HuggingFace 上支持中文的多语言三分类模型：
    cardiffnlp/twitter-xlm-roberta-base-sentiment
输出标签统一映射为：正面 / 中性 / 负面，并附带置信度分数。

当 Transformers/PyTorch 不可用时，自动降级到 snownlp 轻量方案。
"""
import logging
from typing import Any, Dict


class SentimentAnalyzer:
    """情感分析器"""

    def __init__(self, config: Dict[str, Any]):
        cfg = config.get("sentiment", {})
        self.model_name: str = cfg.get(
            "model_name", "cardiffnlp/twitter-xlm-roberta-base-sentiment"
        )
        self.fallback: bool = cfg.get("fallback_to_snownlp", True)
        self.device: int = cfg.get("device", -1)
        self.max_length: int = cfg.get("max_length", 512)
        self.pos_thr: float = cfg.get("snownlp_threshold_pos", 0.6)
        self.neg_thr: float = cfg.get("snownlp_threshold_neg", 0.4)

        # 标签映射表：兼容 negative/neutral/positive 与通用 LABEL_x
        self._label_map = {
            "positive": "正面",
            "neutral": "中性",
            "negative": "负面",
            "LABEL_0": "负面",
            "LABEL_1": "中性",
            "LABEL_2": "正面",
        }

        self._pipeline = None
        self._load_model()

    def _load_model(self) -> None:
        """加载 HuggingFace pipeline，失败时根据配置决定是否抛错"""
        try:
            from transformers import pipeline

            self._pipeline = pipeline(
                "sentiment-analysis",
                model=self.model_name,
                tokenizer=self.model_name,
                device=self.device,
                top_k=None,
            )
            logging.info("HuggingFace 情感模型加载成功：%s", self.model_name)
        except Exception as exc:
            logging.warning("HuggingFace 模型加载失败：%s", exc)
            self._pipeline = None
            if not self.fallback:
                raise RuntimeError(
                    f"情感模型加载失败且未启用 fallback，请检查网络与依赖：{exc}"
                ) from exc
            logging.info("将使用 snownlp 作为备选情感分析方案")

    def _map_label(self, raw_label: str) -> str:
        """将模型原始标签映射为中文三分类标签"""
        key = str(raw_label).strip().lower()
        return self._label_map.get(key, key)

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        对单条文本进行情感分析。

        Returns:
            {
                "sentiment": "正面/中性/负面",
                "confidence": 0.0~1.0,
                "raw_label": 模型原始标签,
                "source": "transformers" / "snownlp" / "error"
            }
        """
        text = (text or "").strip()
        if not text:
            return {
                "sentiment": "中性",
                "confidence": 0.0,
                "raw_label": "",
                "source": "none",
            }

        # 优先使用 HuggingFace 模型
        if self._pipeline is not None:
            try:
                result = self._pipeline(text[: self.max_length], top_k=None)
                # pipeline 对单条输入返回 list[dict]
                if isinstance(result, list) and result and isinstance(result[0], list):
                    result = result[0]
                if not isinstance(result, list) or not result:
                    raise ValueError(f"模型返回格式异常：{result}")

                best = max(result, key=lambda x: x.get("score", 0))
                label = self._map_label(best["label"])
                conf = float(best["score"])
                return {
                    "sentiment": label,
                    "confidence": round(conf, 4),
                    "raw_label": str(best["label"]),
                    "source": "transformers",
                }
            except Exception as exc:
                logging.warning("HuggingFace 推理失败：%s", exc)
                if not self.fallback:
                    raise

        # 备选：snownlp
        try:
            from snownlp import SnowNLP

            score = SnowNLP(text).sentiments  # 0~1，越接近 1 越正面
            if score >= self.pos_thr:
                label = "正面"
                conf = score
            elif score <= self.neg_thr:
                label = "负面"
                conf = 1 - score
            else:
                label = "中性"
                # 越靠近 0.5 越不确定
                conf = 1 - abs(score - 0.5) * 2

            return {
                "sentiment": label,
                "confidence": round(conf, 4),
                "raw_label": f"snownlp:{score:.3f}",
                "source": "snownlp",
            }
        except Exception as exc:
            logging.error("snownlp 情感分析也失败：%s", exc)
            return {
                "sentiment": "中性",
                "confidence": 0.0,
                "raw_label": "error",
                "source": "error",
            }
