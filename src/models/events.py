from typing import List
from llama_index.core.workflow import Event
from src.models.base import Task


class SubTaskEvent(Event):
    task_list: List[Task]


class TaskResultEvent(Event):
    task_result: List[Task]
