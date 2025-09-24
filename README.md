# DeepGraph

GraphDB based QA Agent

## Guide

参考env.example配置自己的.env文件

```
# LLM Client
OPENAI_API_KEY=<YOUR API KEY>
OPENAI_BASE_URL=<YOUR BASE URL>

# Agent Settings
PLANNER_MODEL=qwen-max-latest
WORKER_MODEL=qwen-plus-latest
REVIEWER_MODEL=qwen-turbo

# Nebula Settings
NEBULA_PORT=
NEBULA_HOST=
NEBULA_USER=
NEBULA_PASSWORD=

# VectorDB Settigns
VECTOR_DB_PATH=
```
使用config中的settings进行调用

```
from config.settings import settings

api_key = settings.openai_api_key
base_url = settings.openai_base_url
# 其他配置可以自行在各自的.env中更新并在settings中更新
```

## Structure

- `src/tools` : 工具函数定义，注意 Docstring和类型注解
- `tests` : 所有测试脚本都放在这，工具或者流程的单元测试，以 `test_` 作为前缀命名
- `src/agents` : Agent类的定义与功能
- `src/workflow` : 整体流程调度 + 服务端口定义
- `src/context` : 上下文管理，动态知识注入(Retrieval)
- `src/utils : 常用Utilities`
- `src/models` : 流程或者工具产生的数据结构定义
- `src/prompts` : Agent或者工具使用到的提示词

## Architecture

### UML类图

```mermaid
classDiagram
    %% === 数据模型层 ===
    class Task {
        +string name
        +string description
        +string result
        +string status
        +boolean success
    }
    
    class TaskList {
        +Task[] sequential_tasks
        +Task[] parallel_tasks
    }
    
    class SearchResult {
        +string url
        +string title
        +string content
        +to_md() string
    }
    
    %% === 事件模型层 ===
    class SubTaskEvent {
        +Task[] task_list
    }
    
    class TaskResultEvent {
        +Task[] task_result
    }
    
    %% === 配置层 ===
    class Settings {
        +string nebula_host
        +string nebula_port
        +string nebula_user
        +string nebula_password
        +string openai_api_key
        +string openai_base_url
        +string vector_db_path
        +dict agent_settigns
        +string redis_host
        +string redis_port
        +string task_db
        +string tool_db
        +string tool_cache_expiry
        +string tavily_key
    }
    
    %% === 工具层 ===
    class ToolsUtility {
        <<utility>>
        +_get_json_type(python_type) string
        +tools_to_openai_schema(tools) dict[]
    }
    
    %% === 上下文管理层 ===
    class KnowledgeRetriever {
        +string persist_directory
        +__init__(persist_directory)
        +retrieve(query) string
    }
    
    %% === 代理基类 ===
    class FunctionCallingAgent {
        +string name
        +string description
        +string model
        +dict tools_registry
        +list tools
        +string system_prompt
        +list context_window
        +AsyncOpenAI client
        +tuple args
        +dict kwargs
        +__init__(name, description, model, tools, system_prompt)
        +get_context_window() list
        +add_to_context_window(message)
        +clear_context_window()
        +set_context_window(messages)
        +_handle_tool_call(tool_call) string
        +_run(messages) string
        +_run_stream(messages) AsyncGenerator
        +stream(query) AsyncGenerator
        +run(query) string
    }
    
    %% === 规划代理 ===
    class Planner {
        +AsyncOpenAI client
        +string intention_recognition_prompt
        +string system_prompt
        +KnowledgeRetriever knowledge_retriever
        +__init__()
        +intention_recognition(query) dict
        +plan(query) TaskList
    }
    
    %% === 工作代理 ===
    class Worker {
        +Task assigned_task
        +Context context
        +Redis tool_db
        +Redis task_db
        +__init__(assigned_task, context)
        +_generate_cache_key(tool_call) string
        +_handle_tool_call(tool_call) string
    }
    
    %% === 工作流引擎 ===
    class DeepGraphWorkflow {
        +Planner planner
        +__init__()
        +plan(ev, ctx) SubTaskEvent
        +execute_sequential(ev, ctx) TaskResultEvent
        +execute_parallel(ev, ctx) TaskResultEvent
        +report(ev, ctx) StopEvent
    }
    
    %% === 工具函数 ===
    class ToolFunctions {
        <<functions>>
        +run_code(code) string
        +search_web(query) string
        +calculate_indicator(financial_data, analysis_task) dict
        +call_llm_api(prompt) dict
    }
    
    %% === 继承关系 ===
    Worker --|> FunctionCallingAgent
    
    %% === 组合关系 ===
    Planner *-- KnowledgeRetriever
    Worker *-- Task
    Worker *-- Redis : tool_db
    Worker *-- Redis : task_db
    DeepGraphWorkflow *-- Planner
    TaskList *-- Task
    SubTaskEvent *-- Task
    TaskResultEvent *-- Task
    
    %% === 依赖关系 ===
    Planner ..> TaskList
    Planner ..> Settings
    Worker ..> Settings
    FunctionCallingAgent ..> ToolsUtility
    ToolFunctions ..> SearchResult
    
    %% === 样式 ===
    classDef modelClass fill:#e8f5e8,stroke:#2e7d32,stroke-width:2px
    classDef agentClass fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    classDef workflowClass fill:#e1f5fe,stroke:#0288d1,stroke-width:2px
    classDef toolClass fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    classDef configClass fill:#ffebee,stroke:#d32f2f,stroke-width:2px
    
    class Task,TaskList,SearchResult,SubTaskEvent,TaskResultEvent modelClass
    class FunctionCallingAgent,Planner,Worker agentClass
    class DeepGraphWorkflow workflowClass
    class ToolFunctions,ToolsUtility toolClass
    class Settings,KnowledgeRetriever configClass
```

## TODO

* [ ] 查数工具
* [ ] 指标计算工具
* [ ] 溯源工具 (费用分析相关)
* [ ] 摘要Reporter工具
* [x] Planner (意图识别 + 字任务拆分 + 路由)
* [x] Worker: FunctionCallingAgent/ReActAgent 做工具调用执行任务
* [ ] 并行任务执行实现 (execute_parallel)
* [ ] Gradio / Websocket UI (待定)
