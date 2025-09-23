from concurrent.futures import ThreadPoolExecutor
import orjson
from llama_index.core.workflow import Context, Workflow, StartEvent, StopEvent, step
from src.agents.planner import Planner
from src.agents.worker import Worker
from src.models.events import SubTaskEvent, TaskResultEvent


class DeepGraphWorkflow(Workflow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner = Planner()

    @step
    async def plan(self, ev: StartEvent, ctx: Context) -> SubTaskEvent:
        await ctx.store.set("query", ev.query)

        task_list = await self.planner.plan(ev.query)

        # Record tool call for each task
        for task_type, tasks in task_list.items():
            for task in tasks:
                await ctx.store.set(task.name, [])

        task_count = len(task_list.sequential_tasks) + len(task_list.parallel_tasks)
        await ctx.store.set("task_count", task_count)
        if task_list.sequential_tasks:
            ctx.send_event(SubTaskEvent(task_list=task_list.sequential_tasks))
        if task_list.parallel_tasks:
            ctx.send_event(SubTaskEvent(task_list=task_list.parallel_tasks))

    @step
    async def execute_sequential(
        self, ev: SubTaskEvent, ctx: Context
    ) -> TaskResultEvent:
        previous_task_result = None
        task_report = ""
        for task in ev.task_list:
            print(f"\n=========== Executing task: {task.name}===========\n")
            worker = Worker(task, ctx)
            task_prompt = f"""
            先前的任务结果: {previous_task_result}
            按照要求完成当前任务并输出任务汇报
            """
            async for chunk in worker.stream(task_prompt):
                print(chunk, end="")
                task_report += chunk
            print("\n")

            task.result = task_report
            task.status = "completed"
            task.success = True

            if previous_task_result:
                previous_task_result.append(task)
            else:
                previous_task_result = [task]

        return TaskResultEvent(task_result=ev.task_list)

    @step
    async def execute_parallel(self, ev: SubTaskEvent, ctx: Context) -> TaskResultEvent:
        # TODO Implement parallel execution
        return TaskResultEvent(ev.task_list)

    @step
    async def report(self, ev: TaskResultEvent, ctx: Context) -> StopEvent:
        task_count = await ctx.store.get("task_count")
        task_result_events = ctx.collect_events(ev, [TaskResultEvent] * task_count)
