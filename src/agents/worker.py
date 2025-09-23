from typing import override, Dict, Any, Optional
import hashlib
import orjson
import redis
from openai import AsyncOpenAI
from llama_index.core.workflow import Context
from src.agents.base import FunctionCallingAgent
from src.models.base import Task
from config.settings import settings
from src.prompts.worker_prompts import WORKER_PROMPT
from src.tools.code import run_code


class Worker(FunctionCallingAgent):
    def __init__(
        self, assigned_task: Task, context: Optional[Context] = None, *args, **kwargs
    ):
        self.assigned_task = assigned_task
        system_prompt = WORKER_PROMPT.format(
            task_name=self.assigned_task.name,
            task_description=self.assigned_task.description,
        )
        self.context = context
        # Initialize Redis client for caching
        self.redis_client = redis.Redis(
            host=settings.redis_host,
            port=int(settings.redis_port) if settings.redis_port else 6379,
            db=int(settings.redis_db) if settings.redis_db else 0,
            decode_responses=True,
        )
        super().__init__(system_prompt=system_prompt, *args, **kwargs)

    def _generate_cache_key(self, tool_call: Dict[str, Any]) -> str:
        """
        Generate a cache key based on tool call name and arguments
        """
        function_name = tool_call["function"]["name"]
        function_args = tool_call["function"]["arguments"]

        # Create a consistent string representation for hashing
        cache_data = {"function_name": function_name, "function_args": function_args}

        # Convert to JSON string and create hash
        cache_string = orjson.dumps(cache_data, option=orjson.OPT_SORT_KEYS).decode()
        cache_hash = hashlib.md5(cache_string.encode()).hexdigest()

        return cache_hash

    @override
    async def _handle_tool_call(self, tool_call: Dict[str, Any]) -> str:
        # Generate cache key
        cache_key = self._generate_cache_key(tool_call)

        try:
            # Check if result exists in cache
            cached_result = self.redis_client.get(cache_key)
            if cached_result:
                # Return cached result
                tool_result = cached_result
            else:
                # Execute tool call and cache result
                tool_result = await super()._handle_tool_call(tool_call)
                if not tool_result.startswith("Execute Tool Function Error"):
                    cache_expiry = (
                        int(settings.tool_cache_expiry)
                        if settings.tool_cache_expiry
                        else 86400
                    )
                    self.redis_client.setex(cache_key, cache_expiry, tool_result)
        except Exception as e:
            # If Redis is not available, fall back to direct execution
            print(f"Redis cache error: {e}, falling back to direct execution")
            tool_result = await super()._handle_tool_call(tool_call)

        # Save result to context store
        if self.context:
            worker_result = await self.context.store.get(self.assigned_task.name)
            if worker_result:
                worker_result.append(
                    {
                        "tool_name": tool_call["function"]["name"],
                        "tool_result": tool_result,
                    }
                )
            else:
                worker_result = [
                    {
                        "tool_name": tool_call["function"]["name"],
                        "tool_result": tool_result,
                    }
                ]
            await self.context.store.set(self.assigned_task.name, worker_result)

        return tool_result


if __name__ == "__main__":
    worker = Worker(
        name="worker",
        description="A worker agent",
        model="qwen-turbo",
        tools=[run_code],
        assigned_task=Task(
            name="caculate",
            description="How many Rs in word 'KurtRosenwinkel, ignore case",
        ),
    )

    result = worker.run("Write code to solve the task")
    print(result)
