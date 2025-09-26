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
def indicator_caculate(indicator_type: str):
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