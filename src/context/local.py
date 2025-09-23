from openai import AsyncOpenAI
from typing import List, Dict, Any
from config.settings import settings
from src.context.base import Manager, Retriever


class LocalManager(Manager):
    """
    Local Context Manager: Specifically for a single Agent run
    Manage and augment the context window of a Agent run for better performance & result
    """

    def __init__(
        self,
        model: str,
        persist_directory: str,
        messages: List[Dict[str, Any]] = None,
        retriever: Retriever = None,
        *args,
        **kwargs,
    ):
        self.model = model
        self.persist_directory = persist_directory
        self.messages = messages
        self.retriever = retriever
        self.summarizer = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.args = args
        self.kwargs = kwargs

    async def build_context(
        self, query: str, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if self.retriever:
            retrieved_context = await self.retriever.aretrieve(query, 10)
        else:
            retrieved_context = ""

        augment_message = {
            "role": "assistant",
            "content": f"Relevant Information:\n{retrieved_context}",
        }
        messages.append(augment_message)
        return messages

    async def aappend(self, message: Dict[str, Any]) -> None:
        """
        Async version of append
        """
        self.messages.append(message)
