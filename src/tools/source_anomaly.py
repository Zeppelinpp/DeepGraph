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



def get_anomaly_source(anomaly_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    根据识别出来的异常和产生的异常查询语句，确认是否存在产生异常的备注，关系，特性等
    根据异常查询语句，调用nebula数据库，获取异常数据对应的关系、特性、备注等信息，并返回
    返回json 数据，用于报告考虑异常数据来源，提出解决方案的依据。

    """
    # TODO: 需要查询nebula的自然语言query->anomaly_source["nl4nebula"];返回的查询的凭证摘要、金额等结果，整个json 表示异常
    for anomaly_result in anomaly_results:
        if not anomaly_results or anomaly_results.get("anomaly_query_result") == "数据波动合理，不存在异常情况":
            continue
        anomaly_queries = anomaly_result.get("anomaly_query_result", [])
        if not anomaly_queries:
            logging.info("未生成有效的异常查询，跳过溯源。")

        results = []
        for anomaly in anomaly_queries:
            try:
                logging.info(f"正在执行异常溯源: {anomaly['anomaly']}")
                
                # 调用 nl2nebula 生成查询 & 执行查询
                nebula_res = nebula_query(
                    question=anomaly["nl4nebula"],
                    schema_json=schema_json,
                    limit=20
                )

                # 调用 explain_anomaly 对查询结果做归因分析
                explanation = explain_anomaly(
                    indicator=anomaly.get("anomaly"),
                    anomaly_type=anomaly.get("anomaly_type"),
                    raw_vouchers=nebula_res
                )

                results.append(explanation)

            except Exception as e:
                logging.error(f"溯源失败: {str(e)}", exc_info=True)
                results.append({
                    "anomaly": anomaly.get("anomaly", "未知异常"),
                    "status": "error",
                    "detail": str(e)
                })
    return results