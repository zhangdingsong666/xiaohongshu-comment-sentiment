"""
小红书网页版评论爬虫核心模块

核心思路：
1. 使用 Playwright 模拟真实浏览器访问笔记详情页。
2. 通过监听页面网络响应（response 事件）捕获官方评论区 API 返回的 JSON 数据，
   避免手动破解 x-s/x-t 等签名参数。
3. 自动滚动页面触发懒加载，并尝试点击「展开更多回复」获取楼中楼。
4. 登录态保存到 auth_state.json，后续运行可复用。
"""
import json
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Page, Response
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from utils import random_sleep, ensure_dir


class XHSCrawler:
    """小红书笔记评论爬虫"""

    def __init__(self, config: Dict[str, Any]):
        cfg = config.get("crawler", {})
        self.headless: bool = cfg.get("headless", False)
        self.auth_state_path: str = cfg.get("auth_state_path", "./auth_state.json")
        self.user_agents: List[str] = cfg.get("user_agents", [])
        self.default_timeout: int = cfg.get("default_timeout", 30000)
        self.scroll_pause_min: float = cfg.get("scroll_pause_min", 2.0)
        self.scroll_pause_max: float = cfg.get("scroll_pause_max", 5.0)
        self.max_scrolls: int = cfg.get("max_scrolls", 100)
        self.max_comments: int = cfg.get("max_comments", 0)
        self.max_retries: int = cfg.get("max_retries", 3)
        self.retry_delay: int = cfg.get("retry_delay", 5)
        self.note_base_url: str = cfg.get(
            "note_base_url", "https://www.xiaohongshu.com/explore/{note_id}"
        )

        # 采集结果缓存
        self._comments: List[Dict[str, Any]] = []
        self._seen_comment_ids: set = set()

    # ------------------------------------------------------------------
    # 链接与 ID 处理
    # ------------------------------------------------------------------
    def _choose_user_agent(self) -> Optional[str]:
        """随机选取一个 User-Agent"""
        return random.choice(self.user_agents) if self.user_agents else None

    def extract_note_id(self, url: str) -> str:
        """
        从各类小红书分享链接中提取 note_id。
        支持 /explore/<id>、/discovery/item/<id>、/item/<id> 等常见形态。
        """
        patterns = [
            r"xiaohongshu\.com/explore/([a-zA-Z0-9]+)",
            r"xiaohongshu\.com/discovery/item/([a-zA-Z0-9]+)",
            r"xiaohongshu\.com/item/([a-zA-Z0-9]+)",
        ]
        for pat in patterns:
            match = re.search(pat, url)
            if match:
                return match.group(1)

        # 兜底：取 URL 路径最后一段
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if path:
            return path.split("/")[-1]

        raise ValueError(f"无法从链接中识别小红书笔记 ID：{url}")

    def _build_note_url(self, note_id: str) -> str:
        """根据 note_id 构造标准笔记详情页 URL"""
        return self.note_base_url.format(note_id=note_id)

    # ------------------------------------------------------------------
    # 登录态检测
    # ------------------------------------------------------------------
    def _is_login_page(self, page: Page) -> bool:
        """简单判断当前页面是否被重定向到登录页"""
        url_low = page.url.lower()
        if "login" in url_low:
            return True
        try:
            # 页面中存在「扫码登录」等字样时认为需要登录
            return page.locator("text=扫码登录").count() > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 网络响应监听：核心数据解析
    # ------------------------------------------------------------------
    def _response_handler(self, response: Response) -> None:
        """
        监听评论区 API 响应。
        小红书评论接口 URL 通常包含 comment/page，直接取 response.json() 解析。
        """
        url = response.url
        if not response.ok or "comment/page" not in url:
            return

        try:
            data = response.json()
        except Exception:
            return

        if not isinstance(data, dict):
            return

        api_data = data.get("data", {})
        comments = api_data.get("comments", [])
        if not comments:
            return

        for c in comments:
            self._parse_comment(c, level=1)
            # 部分接口会直接在顶层评论里附带若干子评论
            sub_comments = c.get("sub_comments") or c.get("sub_comment") or []
            for sub in sub_comments:
                self._parse_comment(sub, level=2, parent_id=c.get("id"))

    def _parse_comment(
        self,
        c: Dict[str, Any],
        level: int,
        parent_id: Optional[str] = None,
    ) -> None:
        """将单条评论 JSON 转换为结构化字典并去重"""
        cid = c.get("id")
        if not cid or cid in self._seen_comment_ids:
            return

        content = c.get("content", "")
        # 过滤纯图片/空文本评论
        if not content or not content.strip():
            return

        self._seen_comment_ids.add(cid)

        user_info = c.get("user_info", {}) or {}
        nickname = user_info.get("nickname", "")
        create_time = c.get("create_time", "")
        like_count = c.get("like_count", 0) or 0

        self._comments.append(
            {
                "comment_id": cid,
                "parent_id": parent_id,
                "level": level,
                "nickname": nickname,
                "content": content.strip(),
                "publish_time": create_time,
                "like_count": like_count,
            }
        )

    # ------------------------------------------------------------------
    # 页面交互
    # ------------------------------------------------------------------
    def _scroll_page(self, page: Page) -> bool:
        """向下滚动一次，返回页面高度是否发生变化"""
        previous_height = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        random_sleep(0.5, 1.0)
        new_height = page.evaluate("document.body.scrollHeight")
        return new_height > previous_height

    def _click_expand_replies(self, page: Page) -> int:
        """
        点击「展开更多回复」类按钮，触发子评论接口请求。
        由于 class 名动态变化，这里使用文本包含策略，失败不中断主流程。
        """
        clicked = 0
        try:
            expand_buttons = page.locator(
                "xpath=//div[contains(text(), '展开') and contains(text(), '回复')]"
            ).all()
            for btn in expand_buttons:
                try:
                    if btn.is_visible():
                        btn.click()
                        clicked += 1
                        random_sleep(0.3, 0.8)
                except Exception:
                    continue
        except Exception as exc:
            logging.debug("点击展开回复按钮时出错（可忽略）：%s", exc)
        return clicked

    # ------------------------------------------------------------------
    # 单次采集流程
    # ------------------------------------------------------------------
    def _run_once(self, url: str) -> List[Dict[str, Any]]:
        note_id = self.extract_note_id(url)
        target_url = self._build_note_url(note_id)
        logging.info("目标笔记页面：%s", target_url)

        user_agent = self._choose_user_agent()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )

            context_options: Dict[str, Any] = {}
            if user_agent:
                context_options["user_agent"] = user_agent
                logging.info("本次使用 User-Agent：%s", user_agent)

            # 如果存在历史登录态则复用
            if os.path.exists(self.auth_state_path):
                context_options["storage_state"] = self.auth_state_path
                logging.info("检测到历史登录态，将尝试复用：%s", self.auth_state_path)

            context = browser.new_context(**context_options)
            page = context.new_page()
            page.set_default_timeout(self.default_timeout)

            # 注册响应监听器
            page.on("response", self._response_handler)

            # 访问笔记页面
            try:
                page.goto(target_url, wait_until="networkidle")
            except PlaywrightTimeout:
                logging.warning("页面 networkidle 超时，继续解析已加载内容")

            # 登录态检查
            if self._is_login_page(page):
                logging.warning("当前未登录或登录态失效，请在弹出的浏览器中扫码登录")
                for _ in range(60):  # 最多等待 2 分钟
                    if not self._is_login_page(page):
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError("等待扫码登录超时，请重新运行程序")
                logging.info("登录成功，继续采集")

            # 等待评论区入口出现（小红书页面结构若变更，此处可能超时）
            try:
                page.wait_for_selector("text=评论", timeout=15000)
            except PlaywrightTimeout:
                logging.warning(
                    "未在 15 秒内找到「评论」入口，可能是页面结构变化或加载过慢，将继续尝试滚动"
                )

            # 循环滚动 + 展开子评论
            no_change_count = 0
            for i in range(self.max_scrolls):
                if self.max_comments and len(self._comments) >= self.max_comments:
                    logging.info("已达到最大评论数限制：%d", self.max_comments)
                    break

                has_more = self._scroll_page(page)
                random_sleep(self.scroll_pause_min, self.scroll_pause_max)
                self._click_expand_replies(page)

                if not has_more:
                    no_change_count += 1
                    if no_change_count >= 3:
                        logging.info("连续 3 次滚动无新内容，判定已加载完毕")
                        break
                else:
                    no_change_count = 0

                logging.info(
                    "第 %d 次滚动，当前已采集 %d 条评论", i + 1, len(self._comments)
                )

            # 保存登录态供下次复用
            ensure_dir(os.path.dirname(self.auth_state_path) or ".")
            context.storage_state(path=self.auth_state_path)
            logging.info("登录态已保存至：%s", self.auth_state_path)

            browser.close()

        return self._comments

    # ------------------------------------------------------------------
    # 公共入口：带重试
    # ------------------------------------------------------------------
    def fetch_comments(self, url: str) -> List[Dict[str, Any]]:
        """对外接口：采集指定小红书笔记链接的全部评论"""
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self._comments = []
            self._seen_comment_ids.clear()
            try:
                logging.info("===== 第 %d/%d 次采集尝试 =====", attempt, self.max_retries)
                return self._run_once(url)
            except Exception as exc:
                last_error = exc
                logging.error("第 %d 次采集失败：%s", attempt, exc)
                if attempt < self.max_retries:
                    logging.info("%d 秒后重试...", self.retry_delay)
                    time.sleep(self.retry_delay)

        raise RuntimeError(
            f"采集失败，已达到最大重试次数（{self.max_retries} 次）。最后一次错误：{last_error}"
        )
