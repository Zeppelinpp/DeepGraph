from typing import List
from llama_index.core.workflow import Event
from src.models.base import Task


class SequentialSubTaskEvent(Event):
    task_list: List[Task]


class ParallelSubTaskEvent(Event):
    task_list: List[Task]


class TaskResultEvent(Event):
    task_result: List[Task]
