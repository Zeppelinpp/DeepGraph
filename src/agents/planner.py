from openai import AsyncOpenAI
from llama_index.core.agent.workflow import FunctionAgent
from config.settings import settings
from src.utils.retriever import KnowledgeRetriever
from src.models.base import TaskList
from src.prompts.planner_prompts import PLANNER_PROMPT


class Planner:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.system_prompt = PLANNER_PROMPT
        self.knowledge_retriever = KnowledgeRetriever(persist_directory=settings.vector_db_path)

    async def plan(self, query: str):
        analysis_knowledge = self.knowledge_retriever.retrieve(query)
        user_prompt = f"""{query}\n参考这个分析框架思路进行计划:\n{analysis_knowledge}"""
        response = await self.client.chat.completions.create(
            model=settings.agent_settigns["planner_model"],
            messages=[
                {"role": "system", "content": self.system_prompt.format(analysis_knowledge=analysis_knowledge)},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_object",
            }
        )
        try:
            task_list = TaskList.model_validate_json(response.choices[0].message.content)
            return task_list
        except Exception as e:
            return False
