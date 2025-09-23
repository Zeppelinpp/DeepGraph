from typing import Protocol, List, Dict, Any


class Manager(Protocol):
    def build_context(
        self, query: str, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Augment the context from a given query for LLM

        Args:
            query: The query to augment the context
            messages: The messages to augment the context
        Returns:
            The augmented context in messages format
        """
        pass

    def append(self, message: Dict[str, Any]) -> None:
        """
        Append a message to the context

        Args:
            message: The message to append to the context
        """
        pass

    def compress(self) -> str:
        """
        Compress the context into a string

        Returns:
            The compressed context
        """
        pass

    def prune(self) -> None:
        """
        Prune context into specified size
        """
        pass

    def checkpoint(self) -> None:
        """
        Create checkpoint of context, task status, result for persistence
        """
        pass

    async def abuild_context(
        self, query: str, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Async version of build_context
        """
        pass

    async def aappend(self, message: Dict[str, Any]) -> None:
        """
        Async version of append
        """
        pass

    async def acompress(self) -> str:
        """
        Async version of compress
        """
        pass

    async def aprune(self) -> None:
        """
        Async version of prune
        """
        pass

    async def acheckpoint(self) -> None:
        """
        Async version of checkpoint
        """
        pass


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int) -> str:
        """
        Retrieve context from the retriever

        Args:
            query: The query to retrieve context
            top_k: The number of context to retrieve

        Returns:
            Retrieved context
        """
        pass

    async def aretrieve(self, query: str, top_k: int) -> str:
        """
        Async version of retrieve
        """
        pass
