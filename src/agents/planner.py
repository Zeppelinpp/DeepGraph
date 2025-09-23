import orjson
from openai import AsyncOpenAI
from config.settings import settings
from src.utils.retriever import KnowledgeRetriever
from src.models.base import TaskList
from src.prompts.planner_prompts import PLANNER_PROMPT, INTENTION_RECOGNITION_PROMPT


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
        return orjson.loads(response.choices[0].message.content)

    async def plan(self, query: str):
        intention = await self.intention_recognition(query)
        analysis_knowledge = self.knowledge_retriever.retrieve(intention["intention"])
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
            task_list = TaskList.model_validate(
                orjson.loads(response.choices[0].message.content)
            )
            return task_list
        except Exception as e:
            print(e)
            return False


if __name__ == "__main__":
    import asyncio

    planner = Planner()
    task_list = asyncio.run(planner.plan("本月销售费用是否合理？"))
    print(task_list)
