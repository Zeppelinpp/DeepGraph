from llama_index.core.workflow import Context, Workflow, StartEvent, StopEvent, step
from src.agents.planner import Planner
from src.agents.worker import Worker
from src.agents.reporter import Reporter
from src.models.events import SequentialSubTaskEvent, ParallelSubTaskEvent, TaskResultEvent
from src.prompts.worker_prompts import WORKER_USER_PROMPT
from src.tools.web import search_web
from src.tools.code import run_code
from config.settings import settings


class DeepGraphWorkflow(Workflow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner = Planner()
        self.reporter = Reporter()

    @step
    async def plan(self, ev: StartEvent, ctx: Context) -> SequentialSubTaskEvent | ParallelSubTaskEvent:
        await ctx.store.set("query", ev.query)

        task_list = await self.planner.plan(ev.query)

        # Record tool call for each task
        for task in task_list.sequential_tasks:
            await ctx.store.set(task.name, [])
        for task in task_list.parallel_tasks:
            await ctx.store.set(task.name, [])

        task_count = len(task_list.sequential_tasks) + len(task_list.parallel_tasks)
        await ctx.store.set("task_count", task_count)
        if task_list.sequential_tasks:
            ctx.send_event(SequentialSubTaskEvent(task_list=task_list.sequential_tasks))
        if task_list.parallel_tasks:
            ctx.send_event(ParallelSubTaskEvent(task_list=task_list.parallel_tasks))

    @step
    async def execute_sequential(
        self, ev: SequentialSubTaskEvent, ctx: Context
    ) -> TaskResultEvent:
        previous_task_results = []
        task_report = ""
        for task in ev.task_list:
            print(f"\n=========== Executing task: {task.name}===========\n")
            worker = Worker(
                name="worker",
                description=f"Worker for task: {task.name}",
                model=settings.agent_settigns["worker_model"],
                tools=[search_web, run_code],
                assigned_task=task,
                context=ctx,
            )
            # TODO Retrieve schema context -> Get Schema
            retrieved_context = None
            task_prompt = WORKER_USER_PROMPT.format(
                previous_task_results=previous_task_results,
                retrieved_context=retrieved_context,
                query="",
            )
            async for chunk in worker.stream(task_prompt):
                print(chunk, end="")
                task_report += chunk
            print("\n")

            task.result = task_report
            task.status = "completed"
            task.success = True

            previous_task_results.append(task)

        return TaskResultEvent(task_result=ev.task_list)

    @step
    async def execute_parallel(self, ev: ParallelSubTaskEvent, ctx: Context) -> TaskResultEvent:
        # TODO Implement parallel execution
        return TaskResultEvent(task_result=ev.task_list)

    @step
    async def report(self, ev: TaskResultEvent, ctx: Context) -> StopEvent:
        task_result_events = ctx.collect_events(ev, [TaskResultEvent] * 2)

        task_infos = []

        if not task_result_events:
            return None

        if len(task_result_events) == 2:
            for task_result_event in task_result_events:
                for task in task_result_event.task_result:
                    if task.result:
                        # Get tool call from task
                        tool_calls = await ctx.store.get(task.name)
                        tool_info = [
                            f"- {tool_call['tool_name']}: {tool_call['tool_result']}"
                            for tool_call in tool_calls
                        ]
                        task_info = task.to_md() + "\n" + "\n".join(["工具调用:\n"] + tool_info)
                        task_infos.append(task_info)

            # TODO Report Agent
            query = await ctx.store.get("query")
            report = ""
            report_stream = self.reporter.report(query, "\n".join(task_infos))
            async for chunk in report_stream:
                print(chunk, end="")
                report += chunk
            print("\n")
            return StopEvent(result=report)


async def main():
    workflow = DeepGraphWorkflow(
        timeout=1200,
        verbose=True,
    )
    result = await workflow.run(query="金蝶国际最近半年的财务分析")
    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
