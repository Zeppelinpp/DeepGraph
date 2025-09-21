from pydantic import BaseModel
from typing import Literal, List

class Task(BaseModel):
    task_name: str
    task_description: str
    task_result: str
    task_status: Literal["pending", "in_progress", "completed", "failed"]
    success: bool

class TaskList(BaseModel):
    tasks: List[Task]