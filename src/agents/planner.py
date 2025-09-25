import orjson
from openai import AsyncOpenAI
from config.settings import settings
from src.utils.retriever import KnowledgeRetriever
from src.models.base import TaskList
from src.prompts.planner_prompts import PLANNER_PROMPT, INTENTION_RECOGNITION_PROMPT
from src.utils.logger import logger


class Planner:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.intention_recognition_prompt = INTENTION_RECOGNITION_PROMPT
        self.system_prompt = PLANNER_PROMPT
        self.knowledge_retriever = KnowledgeRetriever(
            persist_directory="config/analysis_frame.json"
        )

    async def intention_recognition(self, query: str):
        # Intention Recognition
        response = await self.client.chat.completions.create(
            model=settings.agent_settigns["planner_model"],
            messages=[
                {"role": "system", "content": self.intention_recognition_prompt},
                {"role": "user", "content": query},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        try:
            return orjson.loads(content)
        except (orjson.JSONDecodeError, TypeError):
            import json
            return json.loads(content)

    async def plan(self, query: str):
        intention = await self.intention_recognition(query)
        framework_key = intention["intention"]
        analysis_knowledge = self.knowledge_retriever.retrieve(framework_key)
        
        # Log framework extraction for traceability
        logger.log_planner_framework_extraction(
            query=query,
            intention=framework_key,
            framework_key=framework_key,
            framework_content=analysis_knowledge,
            retrieval_source="config/analysis_frame.json"
        )
        
        user_prompt = (
            f"""{query}\n参考这个分析框架思路进行计划:\n{analysis_knowledge}"""
        )
        response = await self.client.chat.completions.create(
            model=settings.agent_settigns["planner_model"],
            messages=[
                {
                    "role": "system",
                    "content": self.system_prompt.format(
                        analysis_knowledge=analysis_knowledge
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_object",
            },
        )
        try:
            content = response.choices[0].message.content
            try:
                task_list_data = orjson.loads(content)
            except (orjson.JSONDecodeError, TypeError):
                import json
                task_list_data = json.loads(content)
            
            # Set execution_type for tasks
            for task_data in task_list_data.get("sequential_tasks", []):
                task_data["execution_type"] = "Sequential"
            for task_data in task_list_data.get("parallel_tasks", []):
                task_data["execution_type"] = "Parallel"
            
            task_list = TaskList.model_validate(task_list_data)
            
            # Log task planning completion
            total_tasks = len(task_list.sequential_tasks) + len(task_list.parallel_tasks)
            logger.logger.info(f"[PLANNER:Planning] Generated {total_tasks} tasks | "
                             f"Sequential: {len(task_list.sequential_tasks)} | "
                             f"Parallel: {len(task_list.parallel_tasks)}")
            
            return task_list
        except Exception as e:
            logger.logger.error(f"[PLANNER:Error] Failed to parse task list: {e}")
            print(e)
            return False


if __name__ == "__main__":
    import asyncio

    planner = Planner()
    task_list = asyncio.run(planner.plan("本月销售费用是否合理？"))
    print(task_list)
