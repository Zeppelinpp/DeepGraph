from pydantic import BaseModel
from typing import Literal, List, Optional


class Task(BaseModel):
    name: str
    description: str
    result: Optional[str] = None
    status: Optional[Literal["pending", "in_progress", "completed", "failed"]] = None
    success: Optional[bool] = None


class TaskList(BaseModel):
    sequential_tasks: List[Task]
    parallel_tasks: List[Task]


if __name__ == "__main__":
    task = {"name": "任务名称", "description": "任务描述"}
    task_model = Task.model_validate(task)
    print(task_model)
