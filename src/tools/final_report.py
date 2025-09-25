import os
import json
import logging
from typing import List, Dict, Any, Optional

# 导入必要的库
try:
    import openai
    from dotenv import load_dotenv
    from tenacity import retry, stop_after_attempt, wait_random_exponential
    from openai import RateLimitError, APIError, APIConnectionError
except ImportError as e:
    print(f"错误：缺少必要的库 - {e.name}。请运行 'pip install openai python-dotenv tenacity'")
    raise


# --- 1. 配置加载与客户端初始化 ---

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

load_dotenv()

try:
    client = openai.OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )
    TOOL_MODEL_NAME = os.getenv("TOOL_MODEL", "qwen-max-latest")
    logging.info(f"客户端初始化成功，将使用模型: {TOOL_MODEL_NAME}")
except KeyError as e:
    logging.critical(f"严重错误: 环境变量 {e} 未在 .env 文件中找到。程序将终止。")
    raise ValueError(f"Environment variable {e} not found. Please check your .env file.") from e


# --- 2. 通用LLM调用（Markdown 文本） ---

@retry(
    wait=wait_random_exponential(min=1, max=30),
    stop=stop_after_attempt(3),
    retry_error_callback=lambda rs: logging.error(f"API调用在 {rs.attempt_number} 次尝试后最终失败。")
)
def _call_llm_json(prompt: str) -> Optional[Dict[str, Any]]:
    """
    调用大模型并以 JSON 对象形式返回解析内容。

    Args:
        prompt: 完整提示词

    Returns:
        解析后的 JSON 字典；失败时返回 None。
    """
    try:
        resp = client.chat.completions.create(
            model=TOOL_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            tools=None,
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        if not content:
            logging.error("API响应为空")
            return None
        return json.loads(content)
    except (RateLimitError, APIConnectionError) as e:
        logging.warning(f"可重试API错误: {e}")
        raise
    except APIError as e:
        logging.error(f"不可重试API错误: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"JSON解析失败: {e}")
        return None
    except Exception as e:
        logging.error(f"未知错误: {e}")
        return None


def _call_llm_text(prompt: str) -> Optional[str]:
    """
    调用大模型并返回文本内容。

    Args:
        prompt: 完整提示词

    Returns:
        文本内容；失败时返回 None。
    """
    try:
        resp = client.chat.completions.create(
            model=TOOL_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        return content if content else None
    except Exception as e:
        logging.error(f"LLM文本调用失败: {e}")
        return None


# --- 3. 最终报告生成工具 ---



def generate_final_report(
    analysis_template: str,
    summaries: List[Dict[str, Any]],
    query_data: List[Dict[str, Any]],
    indicator_results: List[Dict[str, Any]],
    report_title: str = "公司财务分析报告（最终版）"
) -> Optional[str]:
    """
    根据动态传入的分析模板，将多个分析小结整合成一篇高质量的最终财务分析报告。

    此函数的核心设计思想是：
    1. 动态模板：报告的结构完全由 `analysis_template` 参数决定，而非硬编码在Prompt中。
    2. 角色扮演：指示LLM扮演首席财务分析师的角色，以提升报告的专业性和口吻。
    3. 内容整合：要求LLM将离散的`summaries`编织成一个连贯的商业故事，而不仅仅是拼接。
    4. 数据追溯：提供`query_data`和`indicator_results`作为备用数据，供LLM在需要时查阅细节。

    Args:
        analysis_template: 用户提供的自然语言或Markdown格式的报告分析框架/模板。
        summaries: 前面各小节summary的结构化结果数组。
        query_data: 原始查询数据，供参考和细节追溯。
        indicator_results: 指标计算结果，供参考和细节追溯。
        report_title: 最终报告标题。

    Returns:
        Markdown格式的完整报告文本；失败则返回None。
    """

    summaries_str = json.dumps(summaries, ensure_ascii=False, indent=2)
    # 将 query_data 和 indicator_results 作为备用上下文信息，供模型追溯细节
    context_data_str = json.dumps({
        "raw_query_data": query_data,
        "indicator_calc_results": indicator_results
    }, ensure_ascii=False, indent=2)

    # --- 优化后的 Prompt ---
    prompt = f"""
你是一位向公司CEO汇报的首席财务分析师（Chief Financial Analyst）。你的核心任务是整合团队成员提交的多个[分析小结]，并严格遵循给定的[分析框架/模板]，撰写一份逻辑连贯、洞察深刻的最终经营分析报告。

**最高指令：**
- **结构遵从**：报告的章节、标题和内容顺序必须严格按照 [分析框架/模板] 的结构来组织。这是你工作的蓝图，不可违背。
- **内容来源**：报告的主要内容和数据，必须源自于 [核心素材：分析小结]。你可以追溯 [备用原始数据] 来获取更精细的数字，但不能脱离小结的核心发现。
- **叙事整合**：不要简单地拼接小结。你需要将各个小结的发现（Findings）、原因（Causality）和风险（Risks）有机地串联起来，讲述一个关于公司本期经营状况的完整故事。
- **格式要求**：最终输出必须是纯粹的 Markdown 文本。不要包含任何解释性文字或JSON代码块。

---

### [报告标题]
{report_title}

---

### [分析框架/模板]
这是你必须遵循的报告结构。请根据此框架谋篇布局。
{analysis_template}

---

### [核心素材：分析小结]
这是你撰写报告的主要内容来源。
{summaries_str}

---

### [备用原始数据]
当小结中的信息不够详细时，可参考此处的原始数据进行补充。
{context_data_str}

---

现在，请开始撰写你的最终报告。请直接输出 Markdown 正文，以 # {report_title} 作为开头。
"""

    return _call_llm_text(prompt)




if __name__ == "__main__":
    # 简单示例""
    sample_template = """
# 1. 本月经营概览
## 1.1 核心财务指标速览 (表格形式)
## 1.2 整体评价与关键问题
# 2. 深度分析：收入与盈利能力
## 2.1 收入增长归因
    - 按产品线分析
    - 按销售区域分析
## 2.2 利润下滑原因探究
    - 成本端压力分析
    - 费用端影响分析
# 3. 管理建议与行动计划
## 3.1 短期应急措施
## 3.2 中长期改进策略
# 4. 风险提示
    """
    sample_summaries = [
    {
        "section_title": "整体经营业绩",
        "qualitative_assessment": "增长强劲但盈利能力承压",
        "key_findings": [
            {"finding": "本月营业收入1,850万元，同比增长15.2%，超出预算2.8%。", "supporting_data": ["营业收入同比增长率"]},
            {"finding": "净利润352万元，同比增长仅5.6%，未达成预算目标（95.1%）。", "supporting_data": ["净利润同比增长率", "净利润预算达成率"]}
        ],
        "causal_analysis": [],
        "risks_and_implications": ["存在“增量不增利”的初步迹象。"]
    },
    {
        "section_title": "盈利能力专项分析",
        "qualitative_assessment": "毛利率受成本上涨影响显著下滑",
        "key_findings": [
            {"finding": "毛利率为42.5%，同比降低1.2个百分点。", "supporting_data": ["毛利率"]}
        ],
        "causal_analysis": [
            {
                "phenomenon": "毛利率下降",
                "cause": "主要原材料价格同比上涨18%，直接拉低了产品毛利空间。",
                "impact_degree": "high",
                "evidence": "原材料采购价格指数"
            }
        ],
        "preliminary_suggestions": ["启动成本控制专项计划，重点关注原材料采购。"]
    }]
    sample_query = [
    {"科目名称": "营业收入", "会计年度": 2025, "会计期间": 8, "本期金额": 18500000.00},
    {"科目名称": "净利润", "会计年度": 2025, "会计期间": 8, "本期金额": 3520000.00}
    ]
    sample_indicators = [
    {"indicator_name": "营业收入同比增长率", "result": 15.2, "unit": "%"},
    {"indicator_name": "净利润同比增长率", "result": 5.6, "unit": "%"},
    {"indicator_name": "净利润预算达成率", "result": 95.1, "unit": "%"},
    {"indicator_name": "毛利率", "result": 42.5, "unit": "%"}
    ]

    print(json.dumps(generate_final_report(
        analysis_template=sample_template,
        summaries=sample_summaries,
        query_data=sample_query,
        indicator_results=sample_indicators,
        report_title="2024年度财务分析报告"
    ), ensure_ascii=False, indent=2))
