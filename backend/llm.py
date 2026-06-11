"""LLM 客户端封装，使用 LangChain 统一接口。

环境变量配置（在启动后端前设置）:
  LLM_API_KEY   - API 密钥（默认使用 OPENAI_API_KEY）
  LLM_BASE_URL  - API 地址（默认 https://api.openai.com/v1）
  LLM_MODEL     - 模型名（默认 gpt-4o-mini）

示例（国内用户用 DeepSeek）:
  export LLM_BASE_URL=https://api.deepseek.com/v1
  export LLM_MODEL=deepseek-chat
  export LLM_API_KEY=<your-api-key>
"""
import json
import os
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


def _llm(**kwargs) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "",
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        **kwargs,
    )


# ── 研究方向分析的输出结构 ──────────────────────────────

class PaperTopic(BaseModel):
    name: str = Field(description="方向名称")
    description: str = Field(description="方向简要说明")
    all_paper_indices: list[int] = Field(description="属于该方向的所有论文索引")
    representative_paper_indices: list[int] = Field(description="最能代表该方向的论文索引")


class TopicAnalysis(BaseModel):
    topics: list[PaperTopic] = Field(description="研究方向列表")


def analyze_topics(papers_data: list[dict]) -> TopicAnalysis:
    """用 LLM 分析论文列表，返回研究方向（含论文分配）。

    兼容不支持 response_format 的模型（如 DeepSeek），
    由调用方手工解析 JSON 并做 Pydantic 校验。
    """
    from prompts import AGENT_ANALYZE_TOPICS

    llm = _llm(temperature=0.3)
    response = llm.invoke([
        {"role": "system", "content": AGENT_ANALYZE_TOPICS + "\n\nAlways respond with valid JSON, no other text."},
        {"role": "user", "content": json.dumps({"papers": papers_data}, ensure_ascii=False)},
    ])

    content = response.content.strip()

    # 处理 LLM 可能用 ```json ... ``` 包裹 JSON 的情况
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    data = json.loads(content)
    return TopicAnalysis(**data)


def report_llm(data: dict) -> str:
    """用 LLM 生成学术总结。返回文本，失败返回空字符串。"""
    from prompts import AGENT_PROFILE_REPORT
    try:
        llm = _llm(temperature=0.5, max_tokens=500)
        resp = llm.invoke([
            {"role": "system", "content": AGENT_PROFILE_REPORT},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ])
        return resp.content.strip()
    except Exception as e:
        print(f"[report_llm] 失败: {e}")
        return ""
