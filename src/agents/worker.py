import hashlib
import orjson
import redis
import time
import json
from typing import override, Dict, Any, Optional
from llama_index.core.workflow import Context
from src.agents.base import FunctionCallingAgent
from src.models.base import Task
from config.settings import settings
from src.prompts.worker_prompts import WORKER_PROMPT
from src.tools.code import run_code
from src.utils.logger import logger


def safe_serialize(data: Any) -> str:
    """
    安全序列化数据，处理bytes和其他不可序列化类型
    """

    def convert_bytes(obj):
        if isinstance(obj, bytes):
            try:
                return obj.decode("utf-8")
            except UnicodeDecodeError:
                import base64
                return f"<bytes:{base64.b64encode(obj).decode('ascii')}>"
        elif isinstance(obj, dict):
            return {k: convert_bytes(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [convert_bytes(item) for item in obj]
        else:
            return obj

    try:
        converted_data = convert_bytes(data)
        return orjson.dumps(converted_data, option=orjson.OPT_SORT_KEYS).decode("utf-8")
    except (TypeError, ValueError, orjson.JSONEncodeError) as e:
        try:
            return json.dumps(
                converted_data, sort_keys=True, ensure_ascii=False, default=str
            )
        except Exception:
            return str(data)


def safe_deserialize(data: str) -> Any:
    """
    安全反序列化数据
    """
    if not isinstance(data, (str, bytes)):
        return data

    try:
        return orjson.loads(data)
    except (orjson.JSONDecodeError, TypeError):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data


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
        self.tool_db = redis.Redis(
            host=settings.redis_host,
            port=int(settings.redis_port) if settings.redis_port else 6379,
            db=int(settings.tool_db) if settings.tool_db else 0,
            decode_responses=True,
        )
        self.task_db = redis.Redis(
            host=settings.redis_host,
            port=int(settings.redis_port) if settings.redis_port else 6379,
            db=int(settings.task_db) if settings.task_db else 0,
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

        # Use safe serialization for cache key generation
        cache_string = safe_serialize(cache_data)
        cache_hash = hashlib.md5(cache_string.encode()).hexdigest()
        return cache_hash

    @override
    async def _handle_tool_call(self, tool_call: Dict[str, Any]) -> str:
        # Generate cache key
        cache_key = self._generate_cache_key(tool_call)

        # Extract tool information for logging
        tool_name = tool_call["function"]["name"]
        # 安全解析参数
        function_arguments = tool_call["function"]["arguments"]
        if isinstance(function_arguments, str):
            tool_args = safe_deserialize(function_arguments)
        else:
            tool_args = function_arguments

        # Determine execution type based on context or task attributes
        execution_type = getattr(self.assigned_task, "execution_type", "Unknown")
        if execution_type == "Unknown":
            # Try to infer from context or use default
            execution_type = "Sequential"  # Default assumption

        # Start timing
        start_time = time.time()

        try:
            # Check if result exists in cache
            cached_result = self.tool_db.get(cache_key)
            if cached_result:
                # Return cached result
                tool_result = cached_result
                duration_ms = 0  # Cache hit, no execution time

                # Log cached tool call
                logger.log_task_tool_call(
                    task_name=self.assigned_task.name,
                    execution_type=execution_type,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=f"[CACHED] {tool_result}",
                    duration_ms=duration_ms,
                )
            else:
                # Execute tool call and cache result
                tool_result = await super()._handle_tool_call(tool_call)
                duration_ms = (
                    time.time() - start_time
                ) * 1000  # Convert to milliseconds

                # Log tool call execution
                logger.log_task_tool_call(
                    task_name=self.assigned_task.name,
                    execution_type=execution_type,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                    duration_ms=duration_ms,
                )

                if not tool_result.startswith("Execute Tool Function Error"):
                    cache_expiry = (
                        int(settings.tool_cache_expiry)
                        if settings.tool_cache_expiry
                        else 86400
                    )
                    self.tool_db.setex(cache_key, cache_expiry, tool_result)

            # Bind tool result to task and save to Redis
            task_name = f"TASK_{self.assigned_task.name}"
            tool_entry = {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "tool_result": tool_result,
                "duration_ms": duration_ms,
                "timestamp": time.time(),
            }
            # Safe serialize to Redis
            self.task_db.rpush(task_name, safe_serialize(tool_entry))

        except Exception as e:
            # If Redis is not available, fall back to direct execution
            duration_ms = (time.time() - start_time) * 1000
            print(f"Redis cache error: {e}, falling back to direct execution")
            tool_result = await super()._handle_tool_call(tool_call)

            # Log the fallback execution
            logger.log_task_tool_call(
                task_name=self.assigned_task.name,
                execution_type=execution_type,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result=f"[FALLBACK] {tool_result}",
                duration_ms=duration_ms,
            )

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
            name="Analyze",
            description="How many Rs in word 'Strawberryrr', ignore case. And what is that number times 5",
        ),
    )

    result = worker.run("Write code to solve the task")
    print(result)
