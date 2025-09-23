import asyncio
import orjson
from typing import Any, Callable, Dict, List
from openai import AsyncOpenAI
from config.settings import settings
from src.utils.tools import tools_to_openai_schema


class FunctionCallingAgent:
    def __init__(
        self,
        name: str,
        description: str,
        model: str,
        tools: List[Callable],
        system_prompt: str = None,
        *args,
        **kwargs,
    ):
        self.name = name
        self.description = description
        self.model = model
        self.tools_registry = {tool.__name__: tool for tool in tools}
        self.tools = tools_to_openai_schema(tools)
        self.system_prompt = system_prompt
        self.context_window = [
            {
                "role": "system",
                "content": self.system_prompt,
            }
        ]
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.args = args
        self.kwargs = kwargs

    def get_context_window(self) -> List[Dict[str, Any]]:
        return self.context_window

    def add_to_context_window(self, message: Dict[str, Any]) -> None:
        self.context_window.append(message)

    def clear_context_window(self) -> None:
        self.context_window = []

    def set_context_window(self, messages: List[Dict[str, Any]]) -> None:
        self.context_window = messages

    async def _handle_tool_call(self, tool_call: Dict[str, Any]) -> str:
        """
        Execute the tool call

        Args:
            tool_call: The tool call to execute

        Returns:
            The result of the tool call
        """
        try:
            function_name = tool_call["function"]["name"]
            function_args = orjson.loads(tool_call["function"]["arguments"])

            # TODO CallBack Function: For Backend & Frontend Communication

            if function_name not in self.tools_registry:
                return (
                    f"Execute Tool Function Error: Function {function_name} not found"
                )

            tool_function = self.tools_registry[function_name]
            if hasattr(tool_function, "__call__"):
                result = tool_function(**function_args)
                if hasattr(result, "__await__"):
                    result = await result

                # TODO Logging & CallBack Function

                return str(result)
            else:
                return f"Execute Tool Function Error: Function {function_name} is not callable"

        except Exception as e:
            # TODO Logging & CallBack Function
            self.kwargs["event_callback"]("tool_error", str(e))
            return f"Execute Tool Function Error: {e}"

    async def _run(self, messages: List[Dict[str, Any]]) -> str:
        """
        Run the Agent without streaming
        """
        current_messages = messages.copy()
        iteration = 0
        while iteration < self.kwargs.get("max_iterations", 5):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=current_messages,
                    tools=self.tools,
                    tool_choice="auto",
                    temperature=0.7
                    if not self.kwargs.get("temperature", None)
                    else self.kwargs["temperature"],
                )

                assistant_message = response.choices[0].message
                current_messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_message.content,
                        "tool_calls": assistant_message.tool_calls,
                    }
                )

                if assistant_message.tool_calls:
                    for tool_call in assistant_message.tool_calls:
                        tool_result = await self._handle_tool_call(
                            tool_call.model_dump()
                        )

                        # Add Tool Result to Current Messages
                        current_messages.append(
                            {
                                "role": "tool",
                                "content": tool_result,
                                "tool_call_id": tool_call.id,
                            }
                        )

                    iteration += 1
                    continue

                else:
                    response_content = (
                        assistant_message.content or "No response from assistant"
                    )
                    return response_content

            except Exception as e:
                # TODO Logging & CallBack Function
                pass
        return "Max iterations reached without final answer"

    async def _run_stream(self, messages: List[Dict[str, Any]]) -> str:
        """
        Run the Agent with streaming, Low Level API

        Args:
            messages: The messages to the Agent

        Yields:
            Chunk of the response from the Agent
        """
        current_messages = messages.copy()
        iteration = 0
        while iteration < self.kwargs.get("max_iterations", 5):
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=current_messages,
                    tools=self.tools,
                    tool_choice="auto",
                    temperature=0.7
                    if not self.kwargs.get("temperature", None)
                    else self.kwargs["temperature"],
                    stream=True,
                )

                assistant_content = ""
                tool_calls = []
                current_tool_call = None
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta:
                        delta = chunk.choices[0].delta

                        if delta.content:
                            assistant_content += delta.content
                            yield delta.content

                        if delta.tool_calls:
                            for tool_call_delta in delta.tool_calls:
                                if (
                                    current_tool_call is None
                                    or tool_call_delta.index
                                    != current_tool_call.get("index")
                                ):
                                    if current_tool_call is not None:
                                        tool_calls.append(current_tool_call)
                                    current_tool_call = {
                                        "index": tool_call_delta.index,
                                        "id": tool_call_delta.id or "",
                                        "type": tool_call_delta.type or "function",
                                        "function": {
                                            "name": tool_call_delta.function.name or "",
                                            "arguments": tool_call_delta.function.arguments
                                            or "",
                                        },
                                    }
                                else:
                                    if tool_call_delta.function:
                                        if tool_call_delta.function.name:
                                            current_tool_call["function"]["name"] += (
                                                tool_call_delta.function.name
                                            )
                                        if tool_call_delta.function.arguments:
                                            current_tool_call["function"][
                                                "arguments"
                                            ] += tool_call_delta.function.arguments

                if current_tool_call is not None:
                    tool_calls.append(current_tool_call)

                assistant_message = {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": tool_calls if tool_calls else None,
                }
                current_messages.append(assistant_message)

                if tool_calls:
                    for tool_call in tool_calls:
                        tool_result = await self._handle_tool_call(tool_call)
                        current_messages.append(
                            {
                                "role": "tool",
                                "content": tool_result,
                                "tool_call_id": tool_call["id"],
                            }
                        )
                    iteration += 1
                    continue
                else:
                    if assistant_content:
                        # TODO Logging & CallBack Function
                        return
            except Exception as e:
                yield f"\n\nError in Agent Run: {e}"
        yield "\n\nMax iterations reached without final answer"

    async def stream(self, query: str):
        """
        Stream the response from the Agent, High Level API

        Args:
            query: The query to the Agent

        Yields:
            Chunk of the response from the Agent
        """
        self.add_to_context_window(
            {
                "role": "user",
                "content": query,
            }
        )
        full_response = ""
        async for chunk in self._run_stream(self.get_context_window()):
            full_response += chunk
            yield chunk

        self.add_to_context_window(
            {
                "role": "assistant",
                "content": full_response,
            }
        )

    def run(self, query: str):
        self.add_to_context_window(
            {
                "role": "user",
                "content": query,
            }
        )
        return asyncio.run(self._run(self.get_context_window()))
