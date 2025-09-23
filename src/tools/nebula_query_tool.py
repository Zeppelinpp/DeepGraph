import os
import json
from typing import List, Dict, Any, Optional

# 使用 openai SDK 进行 API 调用
import openai
# 使用 dotenv 库加载 .env 文件中的环境变量
from dotenv import load_dotenv

# 导入NebulaGraph Python客户端
from nebula3.gclient.net import ConnectionPool
from nebula3.sclient.session import Session

# ================== 配置加载 ==================
# 从 .env 文件加载环境变量到环境中
load_dotenv()

# 初始化 OpenAI 客户端
try:
    client = openai.OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )
    TOOL_MODEL_NAME = os.getenv("TOOL_MODEL", "qwen-max-latest")
except KeyError as e:
    raise ValueError(f"Environment variable {e} not found. Please check your .env file.") from e

# 从环境变量中读取NebulaGraph数据库连接配置
NEBULA_HOST = os.getenv("NEBULA_HOST", "127.0.0.1")
NEBULA_PORT = int(os.getenv("NEBULA_PORT", 9669)) # 端口号需要是整数
NEBULA_USER = os.getenv("NEBULA_USER", "root")
NEBULA_PASSWORD = os.getenv("NEBULA_PASSWORD", "nebula")
NEBULA_GRAPH_SPACE = "financial_reports"

# ----------------------------------------------------------------------------
# 内部辅助函数
# ----------------------------------------------------------------------------
def _build_ngql_prompt(subjects: List[str], periods: List[int]) -> str:
    # ... (这个函数的内部逻辑与之前版本完全相同，无需改动) ...
    schema_description = """
# NebulaGraph Schema 说明：
# 你的任务是将用户的自然语言查询翻译成nGQL(NebulaGraph Query Language)语句。

## 点 (Vertex) Tags:
### `FinancialAccount` (财务科目记录)
- `account_id` (string): 科目编码, 例如 "6602"。
- `account_name` (string): 科目全名, 例如 "销售费用-广告费"。
- `year` (int): 数据对应的年份, 例如 2024。
- `period` (int): 数据对应的期间（月份）, 例如 9。
- `balance_open` (double): 期初本位币。
- `debit_amount` (double): 本期借方本位币。
- `credit_amount` (double): 本期贷方本位币。
- `balance_close` (double): 期末本位币。

## 任务与规则:
1.  根据用户提供的 "会计科目列表" 和 "期间列表"，生成一条能够查询到这些科目在指定年份期间所有详细数据的 nGQL 语句。
2.  你的回答**必须**只返回 nGQL 查询语句本身，不要包含任何额外的解释或Markdown代码块标记 (```)。
3.  查询的目标是 `FinancialAccount` 点。
4.  使用 `LOOKUP` 语句进行查询。确保你已经为 `account_name` 和 `year` 属性创建了索引。
5.  返回 `FinancialAccount` 的所有属性，并将属性名映射为我们下游工具能理解的中文名。
"""
    final_prompt = f"""
{schema_description}
---
# 你的任务:
请为以下用户输入生成 nGQL 语句：

- 科目列表: {json.dumps(subjects, ensure_ascii=False)}
- 期间列表: {periods}
---
# 你的回答 (nGQL):
"""
    return final_prompt


def _generate_ngql_from_llm(subjects: List[str], periods: List[int]) -> Optional[str]:
    """
    调用大模型，根据科目和期间生成nGQL查询语句 (已更新为使用 OpenAI SDK)。
    """
    prompt = _build_ngql_prompt(subjects, periods)
    print("--- [INFO] Sending Prompt for nGQL generation via OpenAI-compatible API ---")
    try:
        response = client.chat.completions.create(
            model=TOOL_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            # 这里不需要JSON模式，因为我们只需要纯文本的nGQL
            temperature=0,
        )
        ngql_query = response.choices.message.content.strip()
        if ngql_query:
            # 移除LLM可能添加的代码块标记
            if ngql_query.startswith("```"):
                ngql_query = ngql_query.strip("```sql\n").strip("```").strip()
            print(f"--- [INFO] Successfully generated nGQL ---\n{ngql_query}")
            return ngql_query
        return None
    except Exception as e:
        print(f"[ERROR] An exception occurred during nGQL generation: {e}")
        return None

# ----------------------------------------------------------------------------
# 查询工具主函数 (此函数无需修改)
# ----------------------------------------------------------------------------
def query_financial_data(
    subjects: List[str],
    periods: List[int],
    connection_pool: ConnectionPool
) -> Optional[List[Dict[str, Any]]]:
    """
    查询工具的主函数，用于从NebulaGraph中获取财务数据。
    """
    ngql_statement = _generate_ngql_from_llm(subjects, periods)
    if not ngql_statement:
        print("[ERROR] Halting execution because nGQL generation failed.")
        return None

    results_list: List[Dict[str, Any]] = []
    try:
        with connection_pool.session_context(NEBULA_USER, NEBULA_PASSWORD) as session:
            session.execute(f"USE `{NEBULA_GRAPH_SPACE}`;")
            print(f"--- [INFO] Executing nGQL on NebulaGraph ---")
            result = session.execute(ngql_statement)

            if not result.is_succeeded():
                print(f"[ERROR] Failed to execute nGQL on NebulaGraph: {result.error_msg()}")
                return None
            
            column_names = result.keys()
            for row in result:
                record = {name: val.as_mixed() for name, val in zip(column_names, row.values)}
                results_list.append(record)
        
        print(f"--- [INFO] Query successful. Fetched {len(results_list)} records. ---")
        return results_list
    except Exception as e:
        print(f"[ERROR] An exception occurred during NebulaGraph query execution: {e}")
        return None

# ----------------------------------------------------------------------------
# 使用示例 (已更新为使用环境变量中的配置)
# ----------------------------------------------------------------------------
if __name__ == '__main__':
    # 1. 初始化NebulaGraph连接池
    try:
        nebula_connection_pool = ConnectionPool()
        # 使用从.env文件加载的配置进行初始化
        nebula_connection_pool.init([(NEBULA_HOST, NEBULA_PORT)], 10)
    except Exception as e:
        print(f"[FATAL] Failed to initialize NebulaGraph connection pool: {e}")
        exit(1)

    # 2. 定义查询参数
    subjects_to_query = ["销售费用-广告费"]
    periods_to_query = [2024, 2023]

    # 3. 调用查询工具主函数
    financial_data = query_financial_data(
        subjects=subjects_to_query,
        periods=periods_to_query,
        connection_pool=nebula_connection_pool
    )

    # 4. 打印结果
    print("\n--- [RESULT] Final Query Output ---")
    if financial_data:
        print(json.dumps(financial_data, indent=2, ensure_ascii=False))
    else:
        print("Query failed or returned no data.")

    # 5. 关闭连接池
    nebula_connection_pool.close()
    print("\n--- [INFO] NebulaGraph connection pool closed. ---")