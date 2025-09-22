# DeepGraph

GraphDB based QA Agent

## Structure

- `src/tools` : 工具函数定义，注意 Docstring和类型注解
- `tests` : 所有测试脚本都放在这，工具或者流程的单元测试，以 `test_` 作为前缀命名
- `src/agents` : Agent类的定义与功能
- `src/workflow` : 整体流程调度 + 服务端口定义
- `src/context` : 上下文管理，动态知识注入(Retrieval)
- `src/utils : 常用Utilities`
- `src/models` : 流程或者工具产生的数据结构定义
- `src/prompts` : Agent或者工具使用到的提示词

## TODO

* [ ] 查数工具
* [ ] 指标计算工具
* [ ] 溯源工具 (费用分析相关)
* [ ] 摘要Reporter工具
* [ ] Planner (意图识别 + 字任务拆分 + 路由)
* [ ] Worker: FunctionCallingAgent/ReActAgent 做工具调用执行任务
* [ ] Gradio / Websocket UI (待定)
