# 小红书评论爬取 + 中文情感三分类

> ⚠️ **合规免责声明（置顶）**
>
> 本项目仅供 **技术学习、学术研究和个人合规使用**，演示如何使用 Playwright 进行浏览器自动化以及如何使用预训练模型进行中文情感分析。
>
> 使用本项目前，请务必阅读并遵守 [小红书用户协议](https://www.xiaohongshu.com/protocols/agreement) 以及中华人民共和国相关法律法规。**任何因使用本项目而产生的账号封禁、数据纠纷、法律风险等，均由使用者自行承担，与本项目作者无关。**
>
> 本项目**不会**、也**不支持**破解平台签名、绕过验证码、伪造请求参数等非法手段。遇到平台风控/登录校验时，请手动扫码登录或停止使用。

---

## 一、项目功能

1. **评论爬取**：输入单条小红书笔记分享链接，使用 Playwright 模拟真实浏览器访问，自动滚动加载评论（含楼中楼回复）。
2. **字段提取**：评论内容、发布者昵称、发布时间、点赞数、评论层级（1=一级评论，2=二级回复）。
3. **情感分析**：对每条评论进行中文情感三分类，输出 **正面 / 中性 / 负面** 标签及置信度分数。
4. **结果导出**：将爬取与分析结果统一导出为 CSV，便于按情感标签筛选查看。
5. **反爬适配**：随机请求延时、User-Agent 轮换、失败自动重试、登录态复用，降低被检测风险。

## 二、技术栈

- **Python 3.10+**
- **Playwright**：模拟浏览器行为，监听官方评论接口获取结构化数据
- **Transformers + PyTorch**：默认使用 HuggingFace 多语言情感三分类模型
- **SnowNLP**：轻量备选方案，无 GPU / 离线环境也能运行
- **Pandas + PyYAML**：配置管理与 CSV 导出

## 三、环境安装

### 1. 克隆/下载项目

```bash
git clone https://github.com/<your-username>/xiaohongshu-comment-sentiment.git
cd xiaohongshu-comment-sentiment
```

### 2. 安装 Python 依赖

建议使用 Python 3.10 或更高版本。

```bash
pip install -r requirements.txt
```

### 3. 安装 Playwright 浏览器驱动

```bash
playwright install chromium
```

> 如果安装浏览器失败，可尝试指定镜像：
> ```bash
> set PLAYWRIGHT_BROWSERS_PATH=0
> playwright install chromium
> ```

## 四、使用教程

### 1. 复制并编辑配置文件

```bash
copy config.example.yaml config.yaml       # Windows
cp config.example.yaml config.yaml         # macOS / Linux
```

主要配置项说明：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `crawler.headless` | 是否无头运行浏览器。首次登录建议 `false` | `false` |
| `crawler.auth_state_path` | 登录态保存路径，复用后可跳过扫码 | `./auth_state.json` |
| `crawler.scroll_pause_min/max` | 滚动后的随机延时范围（秒） | `2.0` / `5.0` |
| `crawler.max_comments` | 最大采集评论数，`0` 表示不限制 | `0` |
| `sentiment.model_name` | HuggingFace 模型名 | `cardiffnlp/twitter-xlm-roberta-base-sentiment` |
| `sentiment.fallback_to_snownlp` | 模型失败时是否回退到 snownlp | `true` |
| `output.default_dir` | 默认 CSV 输出目录 | `./data` |

### 2. 运行主程序

```bash
python src/main.py --url "https://www.xiaohongshu.com/explore/你的笔记ID" --output data/result.csv
```

首次运行会弹出浏览器，请在 **10 秒内** 完成扫码登录。登录态会自动保存到 `auth_state.json`，下次运行时复用。

### 3. 查看结果

导出 CSV 包含以下字段：

| 字段 | 说明 |
|------|------|
| `comment_id` | 评论唯一 ID |
| `parent_id` | 父评论 ID（一级评论为空） |
| `level` | 评论层级：1=一级评论，2=楼中楼回复 |
| `nickname` | 评论发布者昵称 |
| `content` | 评论内容 |
| `publish_time` | 发布时间（原始时间戳/字符串） |
| `like_count` | 点赞数 |
| `sentiment` | 情感标签：正面 / 中性 / 负面 |
| `confidence` | 置信度分数（0~1） |
| `raw_label` | 模型原始输出标签 |
| `source` | 分析来源：`transformers` / `snownlp` |

## 五、项目结构

```
xiaohongshu-comment-sentiment/
├── README.md
├── requirements.txt
├── config.example.yaml
├── .gitignore
├── data/                     # 导出结果目录（已加入 .gitignore）
│   └── .gitignore
└── src/
    ├── __init__.py
    ├── crawler.py            # Playwright 爬虫核心
    ├── sentiment_analyzer.py # 情感分析模块
    ├── main.py               # 命令行入口
    └── utils.py              # 配置/日志/导出等工具函数
```

## 六、常见问题与注意事项

### Q1：为什么第一次运行要扫码？
小红书部分笔记/评论需要登录态才能完整查看。扫码登录后，程序会将浏览器 `storage_state` 保存到 `auth_state.json`，后续运行自动复用。

### Q2：采集到的评论数为 0？
可能原因：
- 链接无效或笔记已被删除/下架。
- 未登录或登录态过期，请删除 `auth_state.json` 后重新扫码。
- 小红书页面结构升级，可在 `src/crawler.py` 中调整响应监听规则或 DOM 选择器。
- 触发平台风控，建议增大 `scroll_pause_min/max`、减少单日运行频次。

### Q3：如何只采集前 N 条评论？
在 `config.yaml` 中设置：

```yaml
crawler:
  max_comments: 200
```

### Q4：没有 GPU，情感分析会不会很慢？
默认模型在 CPU 上运行，单条推理约几十到几百毫秒。若速度不可接受，可：
- 开启 `fallback_to_snownlp: true` 并临时将 `sentiment.model_name` 设为空字符串（会自动回退到 snownlp）。
- 使用更小模型或本地 ONNX 导出（需自行改造）。

### Q5：运行报错 `ModuleNotFoundError`？
请确认：
- Python 版本 ≥ 3.10
- 已执行 `pip install -r requirements.txt`
- 已执行 `playwright install chromium`

### Q6：是否支持无头模式？
支持，将 `crawler.headless` 设为 `true`。但首次登录建议 `false`，否则无法扫码。

## 七、贡献与许可

欢迎提交 Issue 和 PR 改进本项目。请确保贡献内容同样遵守平台规则与法律法规。

本项目采用 [MIT License](LICENSE) 开源。

---

**再次提醒：请合法合规使用本项目，尊重平台规则与创作者权益。**
