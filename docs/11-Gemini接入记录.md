# Gemini 接口接入记录

- 状态：**已完成并验收**
- 日期：2026-08-27
- 依赖：V2 系列方案

## 一、需求

设置中新增 Google Gemini 接口，含传输格式适配，与 DeepSeek 配套切换使用。

## 二、实现

### 2.1 LLM 客户端抽象（llm.py 重构）

```
BaseLLMClient（所有任务方法统一实现）
├── DeepSeekClient   OpenAI 兼容格式（/chat/completions）
└── GeminiClient     Google generateContent REST 格式
```

- **统一抽象**：7 个任务方法（analyze_hotspot/generate_topic_card/format_phrase/decompose_case/pick_hotspots/extract_expressions/parse_fanwen_template）在基类定义，子类只实现 `_chat_json(system, user) -> dict`。
- **输出一致**：所有子类返回完全相同的统一 JSON 结构 → **前端/流水线无感知切换**（热点三层展示、模板卡等与 DeepSeek 完全一样）。
- `build_llm_client(cfg)` 工厂按 `ai_provider` 构建。

### 2.2 Gemini 传输格式

```
POST {base}/v1beta/models/{model}:generateContent?key=API_KEY
请求: {"contents": [{"role":"user","parts":[{"text": system+"\n\n"+user}]}],
       "generationConfig": {"temperature":0.7, "responseMimeType":"application/json"}}
响应: candidates[0].content.parts[0].text  → 统一 JSON
```

- `responseMimeType=application/json` 让模型输出严格 JSON
- **失败处理**：HTTP 4xx/5xx 时提取响应体 `error.message` 报出具体原因（如 "API key not valid"）；不降级回 DeepSeek。

### 2.3 配置与切换

- config 新增：`gemini_api_key`、`gemini_model`（默认 gemini-2.0-flash）
- 设置页：AI 提供商下拉（DeepSeek/Gemini）→ 动态显示对应配置块
- **模型下拉框**：预设选项（gemini-2.0-flash/2.5-flash/2.5-pro、deepseek-v4-flash/pro）+ datalist 支持自定义输入
- **运行中切换生效**：Pipeline.refresh_client() 每次运行前按 config 重建客户端（provider/key 变化才重建）

## 三、验收结果

| 测试 | 结果 |
|---|---|
| `test_gemini_format.py`（新增 5 项：正常响应/HTTP错误带原因/空响应/无key/工厂切换） | ✅ 全过 |
| 端到端（provider=gemini 无 key） | ✅ 报"未配置 Gemini API Key"明确错误，不降级 |
| 全量回归（10 套件） | ✅ 全绿 |

## 四、使用说明

1. 设置 → AI 提供商选 Google Gemini
2. 填 Gemini API Key（[Google AI Studio](https://aistudio.google.com/apikey) 免费申请，Flash 有免费额度）
3. 模型默认 gemini-2.0-flash，可换或自定义
4. 保存后下次流水线自动用 Gemini；失败会报具体原因，不自动切回 DeepSeek

## 五、边界

- 不做按任务分流（同一时刻整个应用用同一提供商）
- 不做自动降级（报错提示用户手动切换）
