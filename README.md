# 公考申论素材助手 V1

个人自用的申论备考素材软件：每日自动更新热点时事 + AI 生成考点分析，配合万能语段库，数据全部存本地 JSON。

## 功能

- **今日热点**：免费源抓取真实新闻 → DeepSeek 生成考点分析（草稿）→ 人工审核入库
- **话题卡**：按主题自动生成高频考点话题卡（背景/意义/问题/对策/金句）
- **语段库**：三维标签（功能位置 × 主题 × 手法）+ 全文搜索 + 一键复制 + 收藏
- **设置**：API Key、每日更新时间与数量、启动补拉

## 运行

```bash
pip install -r requirements.txt
python run.py
```

首次运行自动在 `data/` 初始化本地 JSON（语段库与话题卡种子来自 `seed/`）。

## 使用前必做

在应用「设置」页填写 **DeepSeek API Key**（或兼容 OpenAI 格式的其他服务），否则 AI 生成不可用，只能手动录入。

## 目录结构

```
shenlun/
├── app/
│   ├── main.py        # PySide6 窗口 + 托盘 + 调度
│   ├── server.py      # FastAPI 本地服务 + API
│   ├── store.py       # JSON 数据层
│   ├── pipeline.py    # 每日流水线
│   ├── fetchers.py    # 新闻抓取
│   ├── llm.py         # DeepSeek 客户端
│   └── static/        # 前端（原生 HTML/JS）
├── seed/              # 种子内容
├── data/              # 运行时数据（备份=拷贝此目录）
├── docs/              # 方案文档
└── run.py
```

## 文档

方案与实施记录见 [docs/](docs/README.md)。
