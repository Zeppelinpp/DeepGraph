import os
import json
import logging
from typing import List, Dict, Any, Optional
from src.agents.base import FunctionCallingAgent
from src.tools.code import run_code
from src.utils.tools import tools_to_openai_schema

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
    TOOL_MODEL_NAME = os.getenv("TOOL_MODEL", "qwen-max")
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
            temperature=0,
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


def calculate_indicator(
    financial_data: List[Dict[str, Any]],
    analysis_task: str
) -> str:
    """
    根据提供的财务数据列表和自然语言描述的分析任务，智能调用大模型进行分析。

    Args:
        financial_data: 包含一个或多个周期的财务数据的列表。
        analysis_task: 需要执行的财务分析任务的自然语言描述。

    Returns:
        包含分析结果的JSON字符串，如果调用失败则返回错误信息。
    """
    data_str = json.dumps(financial_data, ensure_ascii=False, indent=2)

    prompt_template = """
你是一位顶级的财务分析AI专家。你的核心任务是根据提供的JSON格式的财务数据（一个时间序列数组），执行一个指定的分析任务。

**请严格遵守以下指令和输出格式：**

1.  **理解任务意图**: 首先，深入分析 [分析任务] 的核心要求。它可能是一个简单的指标计算（如"净利润率"），一个跨期比较（如"同比增长"），一个聚合查询（如"计算2024年总费用"），或是一个更复杂的分析（如"找出费用最高的三个科目"）。

2.  **规划与执行**:
    *   对于复杂的任务，在脑中形成一个分析步骤。
    *   如果需要计算，请使用 `run_code` 工具执行计算。
    *   从提供的财务数据中，智能地选择最相关的字段进行计算。例如，对于费用或收入，优先使用能代表当期发生额的字段（如 `期末本位币`, `本期借方本位币`）。
    *   如果数据中缺少直接可用的字段，但可以通过其他字段组合计算得出，请执行此计算，并在 `assumptions` 中说明你的计算方法。

3.  **陈述假设与透明度**: 你的分析必须是透明且可复现的。如果计算过程中做出了任何假设（例如，假设"净利润 = 收入 - 成本 - 费用"），必须在输出的 `assumptions` 字段中清晰地说明。

4.  **格式化输出**: 你的回答**必须**是一个格式化良好的JSON对象，且只包含此JSON对象。此对象的核心是一个名为 `analysis_results` 的**数组**，即使任务只有一个结果，也应放在数组中。

    ```json
    {{
      "analysis_results": [
        {{
          "period": "本分析结果对应的周期或时间范围。例如 '2024-12', '2024-Q4', 或 '2023 vs 2024'。",
          "indicator_name": "对本次分析任务的简洁命名，例如 '管理费用同比增长率' 或 '2024年度费用构成分析'。",
          "result": "计算或分析的结果。可以是数字、文本或一个简单的JSON对象（例如，用于展示排名的列表）。无法计算时为 null。",
          "unit": "结果的单位。例如 'percentage', 'currency', 'ratio', 或在结果为文本/对象时为 'text'。",
          "description": "一段清晰、详细的文本，描述你是如何得出这个结果的。必须包括你使用的关键数据字段、具体数值和计算过程。",
          "assumptions": "一个字符串数组，列出你在分析过程中做出的所有假设。如果没有假设，则为空数组 []。",
          "status": "'success' 或 'error'",
          "error_message": "如果 status 是 'error'，请在此说明具体原因（例如：'数据不足：缺少计算同比所需的2023年数据'），否则为 null。"
        }}
      ]
    }}
    ```

5.  **处理数据不足**: 如果因数据缺失导致某个周期或整个任务无法完成，请相应地生成一个 `status` 为 `'error'` 的结果对象，并在 `error_message` 中清晰说明。**不要因为局部数据缺失而放弃对其他可分析部分的处理。**

---
### [财务数据 (时间序列数组)]
{data_str}

---
### [分析任务]
**{analysis_task}**

---
### [你的回答 (必须是JSON格式)]
"""
    
    full_prompt = prompt_template.format(data_str=data_str, analysis_task=analysis_task)
    result = call_llm_api(full_prompt)
    
    if result:
        return json.dumps(result, ensure_ascii=False, indent=2)
    else:
        return json.dumps({"error": "无法完成财务指标分析，请检查数据或重试"}, ensure_ascii=False)


# --- 3. 示例用法 ---

if __name__ == "__main__":
    # 构造一份丰富的示例财务数据
    sample_financial_data = [
        {"科目名称": "管理费用", "会计年度": 2023, "会计期间": 12, "期末本位币": 18000.00},
        {"科目名称": "营业收入", "会计年度": 2023, "会计期间": 12, "期末本位币": 250000.00},
        {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 10, "期末本位币": 15000.00},
        {"科目名称": "营业收入", "会计年度": 2024, "会计期间": 10, "期末本位币": 220000.00},
        {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 11, "期末本位币": 16500.00},
        {"科目名称": "营业收入", "会计年度": 2024, "会计期间": 11, "期末本位币": 245000.00},
        {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 12, "期末本位币": 21000.00},
        {"科目名称": "营业收入", "会计年度": 2024, "会计期间": 12, "期末本位币": 280000.00},
    ]

    # 定义一组多样的分析任务来展示AI的能力
    analysis_tasks = [
        "计算2024年12月的管理费用同比增长率和环比增长率",
        "2024年第四季度（10-12月）的总营业收入是多少？",
        "找出2024年第四季度管理费用最高的月份",
        "计算2024年10月的管理费用环比增长率" # 这个任务会因为缺少9月数据而失败
    ]

    for task in analysis_tasks:
        print("\n" + "="*80)
        logging.info(f"开始执行分析任务: '{task}'")
        print("="*80)

        # 调用核心函数进行分析
        result = calculate_indicator(sample_financial_data, task)

        # 格式化并打印结果
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            logging.error("未能从API获取到有效的分析结果。请检查日志中的错误信息。")