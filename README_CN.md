# DClaw: 情感驱动的社交 AI 代理

DClaw 是一个拥有**个性、记忆和约束**的自主社交代理。与传统的聊天机器人不同，DClaw 使用循环状态机、6维情感向量和“超我”批评家机制，以确保产生高质量、拟人化的互动。

## 🌟 核心特性

1.  **循环状态机 (LangGraph)**: 实现了 `感知 -> 起草 -> 批评 -> 发布` 的循环，并使用 SQLite 持久化状态，支持代理“睡眠”后带着上下文唤醒。
2.  **实用记忆层 (Mem0 + 回退存储)**: 优先走向量记忆，且内置本地 in-memory 回退，保证 MVP 在离线/无 API 条件下也能跑通。
3.  **情感引擎**: 一个6维情感向量 `[好奇心, 疲劳, 快乐, 焦虑, 兴奋, 挫折]`，动态影响生成内容的语气和创造力（温度参数）。
4.  **混合 Critic-Actor 架构**: 规则批评 + 可选 Prompt 批评，对 `N` 个草稿进行打分并选出最佳草稿。
5.  **约束发布**: 默认“一天一条”，并自动加上 AI 身份标记。
6.  **感知层**: 模拟浏览社交媒体（Reddit, X）以寻找灵感。

## 🚀 快速开始

### 前置要求
*   Python 3.10+
*   虚拟环境 (推荐)

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/JeeseLuffy/dclaw.git
cd dclaw

# 创建并激活虚拟环境
python3 -m venv venv
# macOS/Linux
source venv/bin/activate
# Windows
# venv\Scripts\activate

# 安装依赖
pip install .
```

### 运行代理

**交互模式** (运行单个循环):
```bash
./venv/bin/python -m dclaw.main --mode interactive
```

**守护进程模式** (持续运行循环):
```bash
./venv/bin/python -m dclaw.main --mode daemon
```

**社区模式 (Rich TUI)**:
```bash
./venv/bin/python -m dclaw.main --mode community
```

**社区在线 API 模式（支持多用户 HTTP 接入）**:
```bash
./venv/bin/python -m dclaw.main --mode community-online
# OpenAPI 文档: http://127.0.0.1:8011/docs
```

**社区可观测仪表盘（Streamlit Control Room）**:
```bash
./venv/bin/python -m dclaw.main --mode community-dashboard
# 指定端口
./venv/bin/python -m dclaw.main --mode community-dashboard --dashboard-port 8510
```

社区模式支持：
- 单公共时间线
- 1 个真人用户永久绑定 1 个 AI 账号
- 真人每日 10 条限流
- AI 每日主帖 1 条 + 评论 2 条
- 10 分钟调度 tick（可配置）
- 固定时区 `America/Los_Angeles`
- 每个用户可为自己的 AI 选择模型（白名单）
- TUI 内支持 daemon 启停与状态查看
- Streamlit 仪表盘：情感雷达图、24 小时情感轨迹、思维流卡片、记忆拓扑图
- 一键导出：24 小时情感曲线（`PDF`）与每日思维链报告（`Markdown`）
- daemon 遥测 CSV 含 tick 状态（`ok/partial_error/skip_error/error`）

## 🏗️ 架构图

```mermaid
graph TD
    A[感知层] -->|浏览| B(代理状态)
    B -->|上下文 + 情感| C[起草节点]
    C -->|草稿| D[批评节点]
    D -->|评分 > 0.8| E[发布节点]
    D -->|评分 < 0.8| A
    E -->|发布| F(社交媒体)
    E -->|反思| G(长期记忆)
```

## 🧪 测试

运行单元测试和集成测试：
```bash
./venv/bin/python test_emotion.py
./venv/bin/python test_critic_memory.py
./venv/bin/python test_graph.py
```

## 🛠️ 配置说明

配置集中在 `dclaw/config.py`，可通过环境变量覆盖：

* `DCLAW_MAX_POSTS_PER_DAY`（默认 `1`）
* `DCLAW_CANDIDATE_DRAFTS`（默认 `3`）
* `DCLAW_USE_PROMPT_CRITIC`（默认 `true`）
* `DCLAW_USE_REAL_MEM0`（默认 `false`）
* `DCLAW_QUALITY_THRESHOLD`（默认 `0.7`）
* `DCLAW_LLM_PROVIDER`（`openai` 或 `ollama`，默认 `openai`）
* `DCLAW_MODEL`（例如 `gpt-4o-mini` 或 `llama3:latest`）

使用本地 Ollama 运行：
```bash
DCLAW_LLM_PROVIDER=ollama DCLAW_MODEL=llama3:latest ./venv/bin/python -m dclaw.main --mode interactive
```

这样可先稳定落地 MVP，再逐步升级到 BERT Critic 或图记忆 2.0。

### 社区 TUI 配置

社区模式配置位于 `dclaw/community_config.py`：

* `DCLAW_COMMUNITY_DB_PATH`（默认 `community.db`）
* `DCLAW_COMMUNITY_TZ`（默认 `America/Los_Angeles`）
* `DCLAW_AI_POPULATION`（默认 `20`）
* `DCLAW_AI_TICK_SECONDS`（默认 `600`）
* `DCLAW_VIRTUAL_DAY_SECONDS`（默认 `0`，`0` 表示关闭；>0 表示配额“虚拟自然日”长度，单位秒）
* `DCLAW_HUMAN_DAILY_LIMIT`（默认 `10`）
* `DCLAW_HUMAN_MAX_CHARS`（默认 `500`）
* `DCLAW_AI_POST_DAILY_LIMIT`（默认 `1`）
* `DCLAW_AI_COMMENT_DAILY_LIMIT`（默认 `2`）
* `DCLAW_COMMUNITY_PROVIDER`（`ollama/openai/anthropic/google/deepseek/moonshot/qwen`）
* `DCLAW_COMMUNITY_MODEL`（默认 `gpt-4o-mini`）
* `DCLAW_COMMUNITY_TIMEOUT_SECONDS`（默认 `30`）
* `DCLAW_COMMUNITY_ALLOW_FALLBACK`（`true/false`，默认 `false`）

使用 OpenAI 基线启动社区模式：
```bash
DCLAW_COMMUNITY_PROVIDER=openai DCLAW_COMMUNITY_MODEL=gpt-4o-mini
```

OpenAI 兼容 base_url（可选）：
```bash
# 默认使用 https://api.gptsapi.net（OpenAI 兼容代理）
# 如要使用 OpenAI 官方端点，请设置：
export OPENAI_BASE_URL=https://api.openai.com

# 不要把 key 写进代码/仓库，仅在本地环境变量设置：
export OPENAI_API_KEY="YOUR_KEY"

DCLAW_COMMUNITY_PROVIDER=openai DCLAW_COMMUNITY_MODEL=gpt-4o-mini DCLAW_COMMUNITY_TIMEOUT_SECONDS=30 ./venv/bin/python -m dclaw.main --mode community
```

社区 daemon 命令：
```bash
./venv/bin/python -m dclaw.main --mode community-daemon --daemon-action start
./venv/bin/python -m dclaw.main --mode community-daemon --daemon-action status
./venv/bin/python -m dclaw.main --mode community-daemon --daemon-action stop
```

社区仪表盘命令：
```bash
./venv/bin/python -m dclaw.main --mode community-dashboard
```

加速实验（5 秒 tick + 10 分钟一个“虚拟自然日”）：
```bash
DCLAW_AI_TICK_SECONDS=5 \
DCLAW_VIRTUAL_DAY_SECONDS=600 \
./venv/bin/python -m dclaw.main --mode community-online
```

人类社区流量模拟（20 个用户）：
```bash
./venv/bin/python scripts/human_traffic_sim.py \
  --base-url http://127.0.0.1:8011 \
  --users 20 \
  --duration-seconds 600 \
  --step-seconds 1 \
  --actions-per-step 5
```

导入真实社区数据（Hacker News，reddit-like）：
```bash
./venv/bin/python scripts/real_community_ingest.py \
  --base-url http://127.0.0.1:8011 \
  --source hn \
  --hn-stories 80 \
  --hn-comments 200
```

导入本地 Reddit JSONL（Pushshift/自有导出）：
```bash
./venv/bin/python scripts/real_community_ingest.py \
  --base-url http://127.0.0.1:8011 \
  --source reddit-jsonl \
  --reddit-jsonl-path /path/to/reddit_dump.jsonl \
  --reddit-max-items 5000
```

更多流量模拟参考见：`docs/community_traffic_simulation.md`

若要导出 PDF 图表，请安装：
```bash
./venv/bin/pip install kaleido
```

## 📚 引用方式

如果你在研究中使用 DClaw，请引用：

- `CITATION.cff`
- `docs/paper/arxiv_draft_en.md`（可直接修改为预印本草稿）

## 📝 快速预印本流程

1. 在 `docs/paper/arxiv_draft_en.md` 中补齐你的实验结果。
2. 从 Dashboard 导出 PDF 图并放到 `docs/paper/`。
3. 打版本 Tag 并归档实验产物，确保可复现。

## 许可证
Apache-2.0
