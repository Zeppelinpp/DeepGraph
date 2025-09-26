import os
import json
import logging
from typing import List, Dict, Any, Optional
from src.agents.base import FunctionCallingAgent
from src.tools.code import run_code
from src.utils.tools import tools_to_openai_schema
from llama_index.core.workflow import Context

# 导入必要的库
try:
    import openai
    from dotenv import load_dotenv
    from tenacity import retry, stop_after_attempt, wait_random_exponential, RetryError
    from openai import RateLimitError, APIError, APIConnectionError
except ImportError as e:
    print(f"错误：缺少必要的库 - {e.name}。请运行 'pip install openai python-dotenv tenacity'")
    exit(1)


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


# --- 2. 核心函数 ---

@retry(
    wait=wait_random_exponential(min=1, max=30),
    stop=stop_after_attempt(3),
    retry_error_callback=lambda retry_state: logging.error(f"API调用在 {retry_state.attempt_number} 次尝试后最终失败。")
)
def call_llm_api(prompt: str) -> Optional[Dict[str, Any]]:
    """
    使用OpenAI兼容的SDK调用大语言模型，并以JSON格式返回结果。
    此函数集成了健壮的错误处理、日志记录和自动重试机制。

    Args:
        prompt (str): 发送给模型的完整提示文本。

    Returns:
        Optional[Dict[str, Any]]: 成功时返回解析后的JSON字典，否则返回None。
    """
    try:
        logging.info("正在向LLM API发送请求...")
        response = client.chat.completions.create(
            model=TOOL_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            tools=tools_to_openai_schema([run_code]),
            tool_choice="auto",
            temperature=0.3,
        )
        
        content = response.choices[0].message.content
        if not content:
            logging.error("API响应内容为空。")
            return None
            
        logging.info("成功接收并解析了来自LLM的响应。")
        return json.loads(content)

    except (RateLimitError, APIConnectionError) as e:
        logging.warning(f"发生可重试的API错误: {e}。Tenacity将进行重试...")
        raise  # 重新引发异常以触发tenacity的重试机制
    except APIError as e:
        logging.error(f"发生不可重试的API错误 (例如，服务器端问题): {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"无法从LLM响应中解码JSON: {e}")
        logging.debug(f"原始响应内容: {content}")
        return None
    except Exception as e:
        logging.error(f"在API调用期间发生未知异常: {e}")
        return None


async def generate_summary_report(
    section_title: str,
    context: Optional[Context] = None
) -> str:
    """
    根据分析思路、查询数据和指标计算结果生成财务分析报告小节。

    Args:
        section_title (str): 报告小节的标题，默认为"财务分析小节"
        context: The context of the workflow
    Returns:
        str: 包含生成报告小节的JSON字符串，如果调用失败则返回错误信息
    """
    #TODO 获取数据
    if context:
        analysis_thought = await context.store.get("analysis_framework", None) # analysis_thought (str): 自然语言分析思路
        query_data = await context.store.get("query_data", None) # query_data (List[Dict[str, Any]]): 从Nebula数据库查询到的原始数据
        indicator_results = await context.store.get("indicator_results", None) # indicator_results (List[Dict[str, Any]]): 指标计算工具返回的计算结果

    if not analysis_thought or not query_data or not indicator_results:
        return "请先使用`nebula_query_tool`工具或者`indicator_calculator`工具获取指标分析数据"
    # 将数据转换为JSON字符串以便在prompt中使用
    query_data_str = json.dumps(query_data, ensure_ascii=False, indent=2)
    indicator_results_str = json.dumps(indicator_results, ensure_ascii=False, indent=2)

    prompt_template = """
你是一位顶级的财务分析顾问（Senior Financial Analyst），你的任务是为一个大的分析报告撰写一个逻辑严密、洞察深刻的分析小节。你不仅仅是数据的搬运工，更是观点的提炼者。

**核心任务：** 根据给定的 [分析思路]、[原始数据] 和 [指标结果]，生成一个结构化的JSON分析摘要。

**分析框架与思考链 (Chain-of-Thought):**
在生成最终JSON前，请在脑中按以下步骤思考：
1.  **数据确认 (Data Validation):** 快速浏览数据，这些数据是否足以支撑 [分析思路]？是否存在明显矛盾或缺失？
2.  **现象总结 (Phenomenon Summary):** 发生了什么？用一两句话描述核心的财务现象。（例如：收入显著增长，但利润率下滑）。
3.  **归因分析 (Causal Analysis):** 为什么会发生？结合数据，从不同维度（如产品、区域、成本项等）寻找最可能的原因。这是最关键的一步。
4.  **影响与风险 (Impact & Risk):** 这个现象意味着什么？可能会带来哪些短期或长期的影响和风险？
5.  **初步建议 (Preliminary Suggestion):** 基于以上分析，可以提出哪些初步的、针对性的建议？

**输出要求：**
- **严格禁止**编造数据。如果数据不足以得出结论，请在 "limitations" 字段中说明。
- 结论必须由提供的数据支撑。
- 输出必须是**一个完整的JSON对象**，严格遵循下面的`"output_format"`结构。

---

### [分析思路]
{analysis_thought}

---

### [原始查询数据]
{query_data_str}

---

### [指标计算结果]
{indicator_results_str}

---

### [报告小节标题]
{section_title}

---

### [你的回答 (必须是严格的JSON格式)]
```json
{{
  "section_title": "{section_title}",
  "qualitative_assessment": "对本节核心发现的定性评估，例如：'增长强劲但盈利能力承压' 或 '成本控制效果显著'",
  "key_findings": [
    {{
      "finding": "关键发现1的文字描述，必须包含具体数据。例如：'本月营业收入同比增长15.2%，达到1,850万元。'",
      "supporting_data": ["指标名称或数据来源1", "指标名称或数据来源2"]
    }},
    {{
      "finding": "关键发现2的文字描述。例如：'毛利率同比下降1.2个百分点至42.5%。'",
      "supporting_data": ["毛利率同比变化"]
    }}
  ],
  "causal_analysis": [
    {{
      "phenomenon": "需要解释的现象，例如：'毛利率下降'",
      "cause": "归因分析得出的核心原因。例如：'主要受原材料成本上涨18%和高毛利产品销售占比下降的共同影响。'",
      "impact_degree": "high/medium/low",
      "evidence": "支撑原因的数据证据。例如：'原材料采购价格指数', '产品A销售额占比'"
    }}
  ],
  "risks_and_implications": [
    "基于分析发现的潜在风险点1，例如：'“增量不增利”的趋势可能影响公司长期盈利能力和股东回报。'",
    "潜在风险点2，例如：'库存周转率下降可能导致资金占用成本增加和存货跌价风险。'"
  ],
  "preliminary_suggestions": [
    "针对问题提出的初步建议1，例如：'建议启动成本控制专项审查，重点关注原材料采购价格。'",
    "初步建议2，例如：'建议复核市场推广策略，评估高费用渠道的投入产出比。'"
  ],
  "data_sources_used": ["引用的具体指标名称列表", "引用的数据表名"],
  "limitations": "分析的局限性，例如：'由于缺乏竞品数据，无法进行市场份额对比分析。'或 '无'",
  "confidence_level": "high"
}}
"""

    full_prompt = prompt_template.format(
        analysis_thought=analysis_thought,
        query_data_str=query_data_str,
        indicator_results_str=indicator_results_str,
        section_title=section_title
    )

    # 直接调用LLM API进行报告生成
    try:
        result = call_llm_api(full_prompt)
        if result:
            return json.dumps(result, ensure_ascii=False, indent=2)
        #TODO 保存数据
        #save


        else:
            return json.dumps({"error": "无法生成财务分析报告小节，请检查数据或重试"}, ensure_ascii=False)
    except Exception as e:
        logging.error(f"生成报告小节时发生错误: {e}")
        return json.dumps({"error": f"生成报告小节时发生错误: {e}"}, ensure_ascii=False)



# --- 3. 示例用法 ---

if __name__ == "__main__":
    # 示例数据
    sample_analysis_thought = "分析2024年第四季度的管理费用变化趋势，重点关注同比和环比增长情况"
    
    sample_query_data = [
        {"科目名称": "管理费用", "会计年度": 2023, "会计期间": 12, "期末本位币": 18000.00},
        {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 10, "期末本位币": 15000.00},
        {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 11, "期末本位币": 16500.00},
        {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 12, "期末本位币": 21000.00},
    ]
    
    sample_indicator_results = [
        {
            "indicator_name": "管理费用同比增长率",
            "result": 16.67,
            "unit": "percentage",
            "description": "2024年12月管理费用相比2023年12月增长16.67%",
            "period": "2024-12"
        },
        {
            "indicator_name": "管理费用环比增长率", 
            "result": 27.27,
            "unit": "percentage",
            "description": "2024年12月管理费用相比11月增长27.27%",
            "period": "2024-12"
        }
    ]

    print("="*80)
    logging.info("开始生成财务分析报告小节")
    print("="*80)

    # 调用核心函数生成报告
    result = generate_summary_report(
        analysis_thought=sample_analysis_thought,
        query_data=sample_query_data,
        indicator_results=sample_indicator_results,
        section_title="2024年第四季度管理费用分析"
    )

    # 格式化并打印结果
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        logging.error("未能生成有效的分析报告小节。请检查日志中的错误信息。")