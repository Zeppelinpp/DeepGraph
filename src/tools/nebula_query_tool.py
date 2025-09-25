import os
import json
from typing import List, Dict, Any, Optional
import re
import openai
from dotenv import load_dotenv

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
NEBULA_GRAPH_SPACE = os.getenv("NEBULA_GRAPH_SPACE", "test")

# ----------------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------------
def _schema_to_text(schema: Dict[str, Any]) -> str:
    lines = []
    space = schema.get("space", NEBULA_GRAPH_SPACE)
    lines.append(f"当前使用的图空间: `{space}`\n")
    lines.append("已存在的点 Tags 及属性:")
    for tag in schema.get("tags", []):
        lines.append(f"- Tag `{tag.get('name')}` (属性数: {tag.get('property_count')})")
        for prop in tag.get("properties", []):
            pname = prop.get("name")
            ptype = prop.get("data_type")
            lines.append(f"  - `{pname}`: {ptype}")
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


def _build_ngql_prompt_for_question(question: str, schema: Dict[str, Any]) -> str:
    schema_text = _schema_to_text(schema)
    # TODO: 待优化: 数据库完成之后
    rules = """
生成可直接执行的 nGQL 查询，仅返回 nGQL 一行或多行，不要解释、不要包裹代码块标记。

重要格式要求：
1. 只使用 MATCH 语句，格式：MATCH (v:标签名) WHERE 条件 RETURN v
2. 标签名和属性名用反引号包围，如：`凭证分录`、`会计年度`
3. 数字比较不要加引号，如：v.`会计年度` == 2024
4. 字符串比较要加引号，如：v.`科目名称` == "现金"
5. 绝对不要使用 LIMIT 或 LOOKUP 语句
6. 让数据库返回所有匹配结果

示例：
MATCH (v:`凭证分录`) WHERE v.`会计年度` == 2024 AND v.`期间` == 12 RETURN v
MATCH (v:`凭证分录`) WHERE v.`科目编码` == "1001" RETURN v
"""
    prompt = f"""
# 任务：将自然语言问题翻译为 nGQL

{rules}

# 数据库结构（供参考）
{schema_text}

# 用户问题：
{question}

# 只输出可执行的 nGQL：
"""
    return prompt


def _generate_ngql_from_llm_by_question(question: str, schema: Dict[str, Any]) -> Optional[str]:
    """
    调用大模型：根据自然语言问题与提供的 schema 生成 nGQL 查询。
    """
    prompt = _build_ngql_prompt_for_question(question, schema)
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




def nebula_query(question: str, schema_json: str, limit: Optional[int]) -> str:
    """
    将自然语言问题转换为 nGQL 并在 NebulaGraph 上执行，返回 JSON 字符串结果。

    参数：
    - question: 自然语言问题，例如“查询2024年期间为12的凭证分录的借方金额前10行”。
    - schema_json: 与当前图空间匹配的 schema JSON（包含 space、tags、properties）。
    - limit: 可选，限制返回行数。

    返回：
    - JSON 字符串（列表），每个元素为一行记录的属性字典；失败时返回错误信息 JSON。
    """
    try:
        schema: Dict[str, Any] = json.loads(schema_json)
    except Exception as e:
        return json.dumps({"error": f"无效的schema_json: {e}"}, ensure_ascii=False)

    ngql_statement = _generate_ngql_from_llm_by_question(question, schema)
    if not ngql_statement:
        return json.dumps({"error": "nGQL 生成失败"}, ensure_ascii=False)

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
        return json.dumps(results_list, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"执行异常: {e}"}, ensure_ascii=False)

# ----------------------------------------------------------------------------
# 使用示例 
# ----------------------------------------------------------------------------
if __name__ == '__main__':
    # 示例：使用用户提供的 schema 和问题
    example_schema = _load_schema_from_file(os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'config', 'nebula_schema.json'))
    question = "有哪些会计科目？只要返回编码和名称, 参考schema"
    print(nebula_query(question, json.dumps(example_schema, ensure_ascii=False), limit=20))