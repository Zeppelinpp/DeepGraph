from openai import AsyncOpenAI
from config.settings import settings
from src.prompts.reporter_prompts import REPORTER_PROMPT, REPORTER_USER_PROMPT

class Reporter:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.agent_settigns["planner_model"]
        self.system_prompt = REPORTER_PROMPT
        self.user_prompt = REPORTER_USER_PROMPT
    
    async def report(self, query: str, task_infos: str):
        user_prompt = self.user_prompt.format(query=query, task_infos=task_infos)
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self.system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        