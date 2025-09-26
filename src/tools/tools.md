# Tools 设计

**涉及Nebula图数据库查询统一调用 `src/utils/nebula.py` 中的 `execute_ngql` 函数**

## 查数工具 `nebula_query`
```python
def nebula_query(node_types: List[str], query: str) -> DataFrame:
    """
    node_types: 查询可能涉及的节点，worker会被提供所有可选node_types然后决定这次查询需要哪些node_types
    query: 查询的目标

    使用 src/utils/nebula.py 中的 get_schema() 工具 获取和相关node_types相关的schema信息, 利用query配合大模型生成nGQL
    查询得到结果后处理数据为DataFrame (pandas或者polars, 推荐使用polars)
    """
    result = ...
    tool_data.set("data", result)
    return result
```

## 指标计算 `indicator_caculate`
```python
def indicator_caculate(indicator_type: str) -> Dict[str, Any]:
    """
    type: 什么类型的指标
    """
    data = tool_data.get("data")
    result = llm_call(data, indicator_type)
    tool_data.set("indicator", result)
    return result
```

## 异常分析 `analysis(命名待定)`
```python
def analysis(types: List[str]):
    """
    types: 哪几种类型的异常需要做分析
    """
    indicator = tool_data.get("indicator")
    result = llm_call(indicator, types)
    tool_data.set("analysis", result)
    return result
```

## 溯源
```python
def ___ () -> DataFrame | str:
    indicator = tool_data.get("indicator")
    data = tool_data.get("data")
    analysis_result = tool_data.get("analysis")

    result = llm_call(indicator, data, analysis_result)
    return result
```

## 小结论summary
```python
def generate_summary_report(section_title: str = "财务分析小节") -> str:
    """
    根据分析思路、查询数据和指标计算结果生成财务分析报告小节。
    
    Args:
        section_title (str): 报告小节的标题，默认为"财务分析小节"
    
    Returns:
        str: 包含生成报告小节的JSON字符串，如果调用失败则返回错误信息
    
    需要获取的数据:
        analysis_thought (str): 自然语言分析思路
        query_data (List[Dict[str, Any]]): 从Nebula数据库查询到的原始数据
        indicator_results (List[Dict[str, Any]]): 指标计算工具返回的计算结果
    """
    # 将数据转换为JSON字符串以便在prompt中使用
    query_data_str = json.dumps(query_data, ensure_ascii=False, indent=2)
    indicator_results_str = json.dumps(indicator_results, ensure_ascii=False, indent=2)
    
    # 使用LLM API生成结构化的财务分析报告小节
    result = call_llm_api(full_prompt)
    return json.dumps(result, ensure_ascii=False, indent=2)
```

## 最终报告生成 `final_report`
```python
def generate_final_report(report_title: str = "公司财务分析报告（最终版）") -> Optional[str]:
    """
    根据动态传入的分析模板，将多个分析小结整合成一篇高质量的最终财务分析报告。
    
    Args:
        report_title (str): 最终报告标题，默认为"公司财务分析报告（最终版）"
    
    Returns:
        Optional[str]: Markdown格式的完整报告文本；失败则返回None
    
    需要获取的数据:
        analysis_template (str): 用户提供的自然语言或Markdown格式的报告分析框架/模板
        summaries (List[Dict[str, Any]]): 前面各小节summary的结构化结果数组
        query_data (List[Dict[str, Any]]): 原始查询数据，供参考和细节追溯
        indicator_results (List[Dict[str, Any]]): 指标计算结果，供参考和细节追溯
    """
    # 将数据转换为JSON字符串
    summaries_str = json.dumps(summaries, ensure_ascii=False, indent=2)
    context_data_str = json.dumps({
        "raw_query_data": query_data,
        "indicator_calc_results": indicator_results
    }, ensure_ascii=False, indent=2)
    
    # 使用LLM API生成最终报告
    return _call_llm_text(prompt)
```
