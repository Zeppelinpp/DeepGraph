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


# --- 3. 异常检测模块 ---
def detect_anomaly(indicator_result: Any) -> Dict[str, List[Dict[str, Any]]]:
    """
    输入: 单个或批量指标的计算结果
    输出: {"anomaly_query_result": List[Dict]} 统一为 list
    """
    if isinstance(indicator_result, dict):
        indicator_text = json.dumps(indicator_result, ensure_ascii=False)
    elif isinstance(indicator_result, list):
        indicator_text = json.dumps(indicator_result, ensure_ascii=False)
    else:
        indicator_text = str(indicator_result)

    prompt = f"""
你是一名资深财务分析师，负责从输入的财务指标结果中识别异常，并输出 JSON。

## 规则
1. 仅处理状态为 "success" 的指标；
2. 异常识别严格遵循下方“异常分类规则”，不扩展、不引申；
3. 无异常时返回空列表 []。

## 异常分类规则

1. 趋势波动类
   - 同比波动：本期值相较去年同期波动 > ±20% → 异常
   - 环比波动：本期值相较上期波动 > ±15% → 异常
   - 连续趋势：连续≥3期同向波动（增/减）且累计幅度>±30% → 异常

2. 结构分析类
   - 成本/费用占收入比例超过历史合理区间或行业均值±20% → 异常
   - 新兴科目（历史未出现）突然出现且金额显著（>10000） → 异常
   - 资产负债率>80% 或 毛利率下降>10% → 异常

3. 同行对标类
   - 指标偏离行业均值 ±30% → 异常

4. 考核/预警阈值类
   - 指标未达预设阈值（如流动比率 < 1，速动比率 < 0.2） → 异常

5. 报表项目/科目逻辑关联类
   - 收入增长但现金流未同步增长 → 异常
   - 收入增长但应收账款大幅增加 > 收入增速 → 异常
   - 销售增长但毛利率下降 > 10% → 异常
   - 成本下降但收入未下降，或利润下降与收入无关 → 异常

6. 预算对比类
   - 收入类指标低于预算 ≥10% → 异常
   - 费用类指标超预算 ≥10% → 异常

7. 典型场景专项类
   - 管理费用/销售费用/研发费用等单月激增 > ±30% → 异常
   - 季节性/政策性因素需要额外说明（如年终奖、政策补贴） → 异常
   - 存货总额同比/环比波动 > ±25% → 异常
   - 库存增加而销量下降 → 异常
   - 单一品类库存占比 >70% → 异常
   - 呆滞品金额 > 总库存10% → 异常
   - 存货周转率低于行业均值30% → 异常
   - 库存周转天数超过历史均值50% → 异常

## 输出要求
- 返回 JSON，键固定为 "anomaly_query_result"，值为数组；
- 每个异常包含:
  - anomaly: 异常描述
  - anomaly_source: 数据来源（如管理成本表、库存周转表）
  - anomaly_type: 异常类别（如环比波动异常、库存周转率异常）

- 无异常时，输出："anomaly_query_result":[]
- 避免任何多余文字，仅返回JSON。

## 输入的内容
{indicator_text}

## 输出示例（正确格式）
    ```json
    {{
      "anomaly_query_result": [
        {{
            "period": "异常出现的周期或时间范围。例如 '2024-12', '2024-Q4', 或 '2023年'。",
            "indicator_name": "管理费用",
            "anomaly_source": "成本管理表"
            "anomaly_type": "环比波动异常",
            "compared_period":"与出现异常比较的时间周期或者范围",如："2024-11",如果没有则不返回
            "anomaly_note": "2024年12月管理费用为21000，较11月16500环比增长27%，超过15%的异常阈值",
        }}
      ]
    }}
    ```

## 错误示例（需避免）
- 生成无异常数据的结果。
"""
    result = call_llm_api(prompt=prompt)
    
    # --- 输出规范化 ---
    if not result or "anomaly_query_result" not in result:
        return {"anomaly_query_result": []}

    anomalies = result["anomaly_query_result"]

    # 如果 LLM 输出字符串，转为空列表
    if isinstance(anomalies, str):
        return {"anomaly_query_result": []}

    if not isinstance(anomalies, list):
        logging.warning("LLM 输出格式异常，已强制转为空列表")
        return {"anomaly_query_result": []}
    return {"anomaly_query_result": anomalies}




# --- 4. 主程序（保持任务执行逻辑，适配新的输出格式） ---
if __name__ == "__main__":
    
    # # 1. 计算指标（真实）
    # indicators = get_indicators()  # List[Dict[str, Any]] 

    # # 2. 生成异常检测的自然语言查询
    # anomaly_query = source_anomaly(indicators)  # str -> Optional[Dict[str, Any]]

    # # 3. 打印结果（格式化输出，便于后续工具调用）
    # logging.info("使用异常分析工具，异常分析结果：")
    # logging.info(json.dumps(anomaly_query, ensure_ascii=False, indent=2))

    try:

        # 示例财务数据（含备注信息，用于生成查询）
        sample_financial_data = [
            {"科目名称": "管理费用", "会计年度": 2023, "会计期间": 12, "期末本位币": 18000.00, "备注": "2023年12月常规管理支出"},
            {"科目名称": "营业收入", "会计年度": 2023, "会计期间": 12, "期末本位币": 250000.00, "备注": "2023年12月产品销售收入"},
            {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 10, "期末本位币": 15000.00, "备注": "2024年10月常规管理支出"},
            {"科目名称": "营业收入", "会计年度": 2024, "会计期间": 10, "期末本位币": 220000.00, "备注": "2024年10月产品销售收入"},
            {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 11, "期末本位币": 16500.00, "备注": "2024年11月常规管理支出"},
            {"科目名称": "营业收入", "会计年度": 2024, "会计期间": 11, "期末本位币": 245000.00, "备注": "2024年11月产品销售收入"},
            {"科目名称": "管理费用", "会计年度": 2024, "会计期间": 12, "期末本位币": 21000.00, "备注": "2024年12月含年终奖金支出", "累计金额": 21000.00},
            {"科目名称": "营业收入", "会计年度": 2024, "会计期间": 12, "期末本位币": 280000.00, "备注": "2024年12月产品销售收入+年底促销收入"},
        ]

        # 分析任务列表
        analysis_tasks = [
            "计算2024年12月的管理费用同比增长率和环比增长率",
            "2024年第四季度（10-12月）的总营业收入是多少？",
            "找出2024年第四季度管理费用最高的月份",
            "计算2024年10月的管理费用环比增长率"
        ]

        # 遍历执行任务
        for task in analysis_tasks:
            print("\n" + "="*80)
            logging.info(f"开始执行分析任务: '{task}'")
            print("="*80)

            # 1. 计算指标（真实）
            result = calculate_indicator(sample_financial_data, task)  # 真实场景启用

            if not result:
                logging.error(f"任务 '{task}' 未返回有效指标数据，跳过异常分析。")
                continue

            # 2. 生成自然语言查询
            logging.info(f"分析任务 '{task}' 的异常数据，生成查询语句...")
            anomaly_query = detect_anomaly(result)

            # 3. 打印结果（格式化输出，便于后续工具调用）
            print("\n【异常分析与自然语言查询结果】")
            print(json.dumps(anomaly_query, ensure_ascii=False, indent=2))

    except Exception as e:
        logging.error(f"主程序执行错误: {str(e)}", exc_info=True)
        print(f"程序执行失败: {str(e)}")