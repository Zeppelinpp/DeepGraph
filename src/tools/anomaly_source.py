import os
import json
import logging
from typing import List, Dict, Any, Optional
# 确保src模块路径正确（若仍报ModuleNotFoundError，参考之前的路径修复方案）
try:
    from src.agents.base import FunctionCallingAgent
    from src.tools.code import run_code
    from src.utils.tools import tools_to_openai_schema
    from src.tools.indicator_calculator import calculate_indicator
    from src.utils.logger import get_logger
    from src.utils.nebula import execute_ngql, get_schema
except ImportError as e:
    logging.error(f"src模块导入失败: {str(e)}，请检查模块路径配置")
    exit(1)
import traceback

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
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL"),
    )
    TOOL_MODEL_NAME = os.getenv("TOOL_MODEL", "qwen-max")
    logging.info(f"客户端初始化成功，将使用模型: {TOOL_MODEL_NAME} 进行异常分析与查询生成")
except KeyError as e:
    logging.critical(f"严重错误: 环境变量 {e} 未在 .env 文件中找到。程序将终止。")
    raise ValueError(f"Environment variable {e} not found. Please check your .env file.") from e
except Exception as e:
    logging.critical(f"客户端初始化失败: {str(e)}")
    exit(1)


# --- 2. LLM调用函数（保持重试逻辑和错误处理） ---
@retry(
    wait=wait_random_exponential(min=1, max=30),
    stop=stop_after_attempt(3),
    retry_error_callback=lambda retry_state: logging.error(
        f"API调用在 {retry_state.attempt_number} 次尝试后最终失败。错误: {str(retry_state.outcome.exception())}"
    )
)
def call_llm_api(prompt: str) -> Optional[Dict[str, Any]]:
    try:
        logging.info("正在向LLM API发送请求...")
        response = client.chat.completions.create(
            model=TOOL_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,  # 低随机性确保查询描述准确
        )
        
        content = response.choices[0].message.content.strip()
        if not content:
            logging.error("API响应内容为空。")
            return None
            
        logging.info("成功接收并解析LLM响应。")
        return json.loads(content)

    except (RateLimitError, APIConnectionError) as e:
        logging.warning(f"可重试API错误: {str(e)}，将触发重试...")
        raise
    except APIError as e:
        logging.error(f"不可重试API错误（服务器端问题）: {str(e)}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"LLM响应JSON解码失败: {str(e)}")
        logging.debug(f"原始响应内容: {content[:200]}...")
        return None
    except Exception as e:
        logging.error(f"API调用未知异常: {str(e)}")
        return None


def _build_ngql_prompt_for_question(question: str, schema: Dict[str, Any]) -> str:
    """
    构建 prompt，强制 LLM 输出 JSON 格式，键为 'ngql'，值为一个 list[str]
    """
    rules = """
你是一个 nGQL 生成器。
- 只输出 JSON 对象，不要输出解释或额外文字；
- JSON 格式固定为: { "ngql": ["..."] }
- 每条查询必须是可直接执行的 nGQL；
- 使用 MATCH (v:`标签名`) WHERE 条件 RETURN v；
- 标签名、属性名用反引号；
- 数字不用引号，字符串要用引号；
- 不要使用 LIMIT，不要用 LOOKUP；
- 查询只针对凭证相关节点，如 `凭证分录`、`科目余额`；
- 如果结果可能太多，先只返回凭证编号 (如 v.`凭证编号`)，再做二次查询。
"""
    prompt = f"""
# 任务：将自然语言问题翻译为 nGQL 查询，输出 JSON 格式。

{rules}

# 数据库 Schema 参考：
{json.dumps(schema, ensure_ascii=False)}

# 用户问题：
{question}

# 输出示例：
{{
  "ngql": [
    "MATCH (v:`凭证分录`) WHERE v.`会计年度` == 2024 AND v.`期间` == 12 RETURN v.`凭证编号`"
  ]
}}
"""
    return prompt


def _generate_ngql_from_llm_by_question(question: str, schema: Dict[str, Any]) -> Optional[List[str]]:
    """
    调用 LLM：根据自然语言问题与 schema 生成 nGQL 查询（list[str]）
    """
    prompt = _build_ngql_prompt_for_question(question, schema)
    try:
        ngql_out = call_llm_api(prompt)  # 期望返回 dict
        if ngql_out and "ngql" in ngql_out:
            return ngql_out["ngql"]
        return None
    except Exception as e:
        logging.error(f"nGQL 生成失败: {str(e)}")
        return None


def anomaly_source(
    anomaly_results: List[Dict[str, Any]], 
    use_llm: bool = False, 
    limit: int = 50, 
    min_amount: float = 1000
) -> List[Dict[str, Any]]:
    """
    对异常结果进行溯源查询，返回异常及其来源数据。
    
    Args:
        anomaly_results: 异常检测输出结果
        use_llm: 是否使用 LLM 生成自然语言查询（默认 False，走规则拼接）
        limit: 查询返回上限
        min_amount: 过滤条件，金额小于此值的凭证将被忽略
    """
    if not anomaly_results:
        return []

    queries = []
    for anomaly in anomaly_results:
        if use_llm:
            # 调用 LLM 生成自然语言查询
            prompt = f"""
你是一名财务分析师，需要根据异常信息生成自然语言查询。
要求：
- 输出 JSON，键为 "query"；
- 必须包含：周期(period)、科目名称(indicator_name)、凭证、金额、备注、摘要；
- 如果有 compared_period，则生成涉及两期的查询；
- 不要输出分析/原因性描述。
异常信息：
{json.dumps(anomaly, ensure_ascii=False)}
"""
            llm_out = call_llm_api(prompt)
            query_text = llm_out.get("query", f"查询 {anomaly.get('period')} {anomaly.get('indicator_name')} 相关凭证")
        else:
            # 规则拼接
            query_text = f"查询 {anomaly.get('indicator_name')} 在 {anomaly.get('period')} 及 {anomaly.get('compared_period','')} 的凭证、金额、备注、摘要"

        queries.append({
            "anomaly": anomaly.get("anomaly"),
            "anomaly_type": anomaly.get("anomaly_type"),
            "anomaly_source": anomaly.get("anomaly_source"),
            "query_text": query_text
        })

    # --- 调用 nl2nebula + Nebula 执行 ---
    results = []
    for q in queries:
        try:
            schema = get_schema(["凭证分录","科目余额"])  # Dict
            ngql_list = _generate_ngql_from_llm_by_question(q["query_text"], schema) # List[str]
            print("--- [INFO] Sending Prompt for nGQL generation via OpenAI-compatible API ---")
            print(f"{ngql_list}")
            nebula_result = []
            if ngql_list:
                for query in ngql_list:

                    res = execute_ngql(query)
                    print(f"execute result:{res}")
                    if not res:
                        continue
                    nebula_result.extend(res)

        except Exception as e:
            logging.error(f"Nebula 查询失败: {str(e)}")
            nebula_result = None

        results.append({
            "anomaly": q["anomaly"],
            "anomaly_type": q["anomaly_type"],
            "anomaly_source": q["anomaly_source"],
            "query_text": q["query_text"],
            "anomaly_source_data": nebula_result
        })

    return results



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("nebula").setLevel(logging.WARNING)
    test_anomaly_results = [
    {
      "period": "2024-12",
      "indicator_name": "管理费用",
      "anomaly_source": "成本管理表",
      "anomaly_type": "环比波动异常",
      "compared_period": "2024-11",
      "anomaly_note": "2024年12月管理费用为21000，较11月16500环比增长27%，超过15%的异常阈值"
    },
    {
      "period": "2024-Q4",
      "indicator_name": "库存周转天数",
      "anomaly_source": "库存管理表",
      "anomaly_type": "同比异常",
      "compared_period": "2023-Q4",
      "anomaly_note": "2024年Q4库存周转天数为65天，同比去年同期40天上升62%，库存积压风险增加"
    },
    {
      "period": "2023年",
      "indicator_name": "研发费用",
      "anomaly_source": "研发成本表",
      "anomaly_type": "结构异常",
      "anomaly_note": "2023年研发费用占营业收入比重为28%，远高于行业平均水平15%，存在结构性偏差"
    }
    ]


    res = anomaly_source(anomaly_results=test_anomaly_results,use_llm=False)
    print(res)
