import os
import json
from typing import List, Dict, Any, Optional
import re
import openai
from dotenv import load_dotenv

from src.utils.nebula import get_schema
import pandas as pd
from llama_index.core.workflow import Context
from nebula3.gclient.net import ConnectionPool
from nebula3.Config import Config

load_dotenv()


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
NEBULA_GRAPH_SPACE = os.getenv("NEBULA_GRAPH_SPACE", "jsb")
NEBULA_QUERY_TIMEOUT = 1000

# ----------------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------------
def _schema_to_text(schema: Dict[str, Any]) -> str:
    lines = []
    space = schema.get("space", NEBULA_GRAPH_SPACE)
    lines.append(f"当前使用的图空间: `{space}`\n")
    lines.append("已存在的点 Tags 及属性:")
    for tag in schema.keys():
        lines.append(f"- Tag `{tag}` (属性数: {len(schema[tag].get('properties', []))})")
        for prop in schema[tag].get("properties", []):
            lines.append(f"  - `{prop}`")
    lines.append("(注意：当前未建立边/关系，查询仅限点级检索)")
    return "\n".join(lines)

def _load_schema_from_file(path: str) -> Dict[str, Any]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        schema_obj = raw.get('schema') or {}
        tags = []
        for tag_name, tag_info in schema_obj.items():
            props = tag_info.get('properties') or []
            tags.append({
                'name': tag_name,
                'property_count': len(props),
                'properties': [{'name': p, 'data_type': 'string'} for p in props]
            })
        return {'space': NEBULA_GRAPH_SPACE, 'tags': tags}
    except Exception as e:
        print(f"[WARN] Failed to load schema file: {e}")
        return {'space': NEBULA_GRAPH_SPACE, 'tags': []}


def _build_ngql_prompt_for_question(question: str, schema: Dict[str, Any], limit: Optional[int]) -> str:
    schema_text = _schema_to_text(schema)
    # TODO: 待优化: 数据库完成之后
    rules = """
生成可直接执行的 nGQL 查询，仅返回 nGQL 一行或多行，不要解释、不要包裹代码块标记。

重要格式要求：
1. WHERE 语句中使用 `.` 来访问嵌套属性，如：v.`凭证分录`.`会计年度` == 2024
2. RETURN 语句中使用 `.` 来访问嵌套属性，如：v.`凭证分录`.`需要返回的属性名`
3. NebulaGraph的版本是3.10, 请使用相应的NGQL语法

示例：
MATCH (v:`凭证分录`) WHERE v.`凭证分录`.`会计年度` == 2024 AND v.`凭证分录`.`期间` == 12 RETURN v.`凭证分录`.`需要返回的属性名` LIMIT ["需要限制的条数"] // 替换为实际属性名，如"凭证号"
MATCH (v:`凭证分录`) WHERE v.`凭证分录`.`科目编码` == "1001" RETURN v.`凭证分录`.`需要返回的属性名` LIMIT ["需要限制的条数"]
"""
    prompt = f"""
# 任务：将自然语言问题翻译为 nGQL

{rules}

# 查询节点schema
{schema_text}

# 用户问题：
{question}

# 需要限制的条数
{limit}

# 根据用户问题和节点schema，选择需要分析的tag和property，只输出可执行的 nGQL：
"""
    return prompt


def _generate_ngql_from_llm_by_question(question: str, node_types:List[str], limit: Optional[int]) -> Optional[str]:
    """
    调用大模型：根据自然语言问题与提供的 schema 生成 nGQL 查询。
    """
    schema = get_schema(node_types)
    prompt = _build_ngql_prompt_for_question(question, schema, limit)
    print("--- [INFO] Sending Prompt for nGQL generation via OpenAI-compatible API ---")
    try:
        response = client.chat.completions.create(
            model=TOOL_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            # 这里不需要JSON模式，因为我们只需要纯文本的nGQL
            temperature=0,
        )
        ngql_query = response.choices[0].message.content.strip()
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




async def nebula_query(question: str, node_types: List[str], limit: Optional[int]=NEBULA_QUERY_TIMEOUT, context: Optional[Context] = None) -> str:
    """
    Nebula图数据库查询工具，根据输入的自然语言问题和节点类型生成nGQL并在NebulaGraph上执行，返回Markdown格式的结果。

    参数：
    - question: 查询任务， 例如“查询2024年期间为12的凭证分录的借方金额前10行”。
    - node_types: 节点类型，例如["凭证分录"]。
    - limit: 可选，限制返回行数。

    返回：
    - Markdown格式的结果，每个元素为一行记录的属性字典；失败时返回错误信息。
    """

    ngql_statement = _generate_ngql_from_llm_by_question(question, node_types, limit)
    if not ngql_statement:
        return 'error: nGQL 生成失败'

    # 直接使用大模型生成的 nGQL，不再进行复杂清洗

    results_list: List[Dict[str, Any]] = []
    try:
        pool = ConnectionPool()
        config = Config()
        config.max_connection_pool_size = 10
        pool.init([(NEBULA_HOST, NEBULA_PORT)], config)
        with pool.session_context(NEBULA_USER, NEBULA_PASSWORD) as session:
            session.execute(f"USE `{NEBULA_GRAPH_SPACE}`;")
            print("--- [INFO] Executing nGQL on NebulaGraph ---")
            print(ngql_statement)
            result = session.execute(ngql_statement).as_primitive()
            for row in result:
                results_list.append(row)

        pool.close()
        result = pd.DataFrame(results_list).to_markdown(index=False)
        # todo save result
        if context:
            await context.store.set("query_data", results_list)

        return result
    except Exception as e:
        return f"[ERROR] An exception occurred during nGQL execution: {e}"

# ----------------------------------------------------------------------------
# 使用示例 
# ----------------------------------------------------------------------------
if __name__ == '__main__':
    # 示例：使用用户提供的 schema 和问题
    example_schema = _load_schema_from_file(os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'config', 'nebula_schema.json'))
    question = "有哪些凭证？只要返回编码和名称, 参考schema"
    print(nebula_query(question, node_types=["凭证分录"], limit=10))
