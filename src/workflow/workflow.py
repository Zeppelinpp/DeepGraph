import asyncio
from llama_index.core.workflow import Context, Workflow, StartEvent, StopEvent, step
from src.agents.planner import Planner
from src.agents.worker import Worker
from src.agents.reporter import Reporter
from src.models.events import (
    SequentialSubTaskEvent,
    ParallelSubTaskEvent,
    TaskResultEvent,
)
from src.prompts.worker_prompts import WORKER_USER_PROMPT
from src.tools.web import search_web
from src.tools.code import run_code
from config.settings import settings
from src.utils.logger import logger
from src.utils.web_logger import web_logger


class DeepGraphWorkflow(Workflow):
    def __init__(self, *args, **kwargs):
        self.planner = Planner()
        self.reporter = Reporter()
        super().__init__(timeout=12000, verbose=True)

    @step
    async def plan(
        self, ev: StartEvent, ctx: Context
    ) -> SequentialSubTaskEvent | ParallelSubTaskEvent:
        logger.log_workflow_step("plan", "StartEvent", f"Query: {ev.query}")

        await ctx.store.set("query", ev.query)

        task_list = await self.planner.plan(ev.query)

        # Record tool call for each task
        for task in task_list.sequential_tasks:
            await ctx.store.set(task.name, [])
        for task in task_list.parallel_tasks:
            await ctx.store.set(task.name, [])

        task_count = len(task_list.sequential_tasks) + len(task_list.parallel_tasks)
        await ctx.store.set("task_count", task_count)

        logger.log_workflow_step(
            "plan",
            "TasksGenerated",
            f"Total: {task_count} (Sequential: {len(task_list.sequential_tasks)}, Parallel: {len(task_list.parallel_tasks)})",
        )

        if task_list.sequential_tasks:
            ctx.send_event(SequentialSubTaskEvent(task_list=task_list.sequential_tasks))
        if task_list.parallel_tasks:
            ctx.send_event(ParallelSubTaskEvent(task_list=task_list.parallel_tasks))

    async def _execute_single_task_async(
        self, worker: Worker, task, task_prompt: str
    ) -> str:
        """
        Helper method to execute a single task asynchronously with proper cancellation handling
        """
        try:
            return await worker.async_run(task_prompt)
        except asyncio.CancelledError:
            print(f"Task {task.name} was cancelled")
            raise  # Re-raise to allow proper cancellation propagation
        except KeyboardInterrupt:
            print(f"Task {task.name} was interrupted by user")
            raise asyncio.CancelledError("Task interrupted by user")
        except Exception as e:
            print(f"Error executing task {task.name}: {e}")
            return f"Task execution failed: {e}"

    @step
    async def execute_sequential(
        self, ev: SequentialSubTaskEvent, ctx: Context
    ) -> TaskResultEvent:
        logger.log_workflow_step(
            "execute_sequential",
            "SequentialSubTaskEvent",
            f"Processing {len(ev.task_list)} sequential tasks",
        )

        previous_task_results = []
        task_report = ""
        for task in ev.task_list:
            # Log task execution start
            logger.log_task_execution_start(task.name, "Sequential", task.description)

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

            # Log task execution end
            logger.log_task_execution_end(
                task.name, "Sequential", task.status, task.success
            )

            previous_task_results.append(task)

        return TaskResultEvent(task_result=ev.task_list)

    @step
    async def execute_parallel(
        self, ev: ParallelSubTaskEvent, ctx: Context
    ) -> TaskResultEvent:
        logger.log_workflow_step(
            "execute_parallel",
            "ParallelSubTaskEvent",
            f"Processing {len(ev.task_list)} parallel tasks",
        )

        # Log start of parallel tasks
        for task in ev.task_list:
            logger.log_task_execution_start(task.name, "Parallel", task.description)

        # Implement true async parallel execution with proper cancellation handling
        tasks = []
        for task in ev.task_list:
            print(f"\n=========== Executing task: {task.name} (parallel)===========\n")
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
                previous_task_results=[],
                retrieved_context=retrieved_context,
                query="",
            )
            # Use async_run instead of run to avoid event loop issues
            tasks.append(self._execute_single_task_async(worker, task, task_prompt))

        # Execute all tasks concurrently with proper exception handling
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            # Handle graceful cancellation
            logger.log_workflow_step(
                "execute_parallel", "Cancelled", "Parallel tasks were cancelled"
            )
            # Cancel all remaining tasks
            for task_coroutine in tasks:
                if hasattr(task_coroutine, "cancel"):
                    task_coroutine.cancel()
            # Set all tasks as cancelled
            for task in ev.task_list:
                task.result = "Task was cancelled"
                task.status = "cancelled"
                task.success = False
                logger.log_task_execution_end(
                    task.name, "Parallel", task.status, task.success
                )
            raise

        # Process results and log completion
        for task, result in zip(ev.task_list, results):
            if isinstance(result, asyncio.CancelledError):
                task.result = "Task was cancelled"
                task.status = "cancelled"
                task.success = False
            elif isinstance(result, Exception):
                task.result = f"Task failed with error: {result}"
                task.status = "failed"
                task.success = False
            else:
                task.result = result
                if result == "Max iterations reached without final answer":
                    task.status = "failed"
                    task.success = False
                else:
                    task.status = "completed"
                    task.success = True

            # Log task completion
            logger.log_task_execution_end(
                task.name, "Parallel", task.status, task.success
            )

        return TaskResultEvent(task_result=ev.task_list)

    @step
    async def report(self, ev: TaskResultEvent, ctx: Context) -> StopEvent:
        task_result_events = ctx.collect_events(ev, [TaskResultEvent] * 2)

        task_infos = []
        if task_result_events:
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
                            task_info = (
                                task.to_md()
                                + "\n"
                                + "\n".join(["工具调用:\n"] + tool_info)
                            )
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

    async def run_with_web_logging(self, query: str):
        """Run workflow and enable Web logging"""
        # Start Web session
        session_id = web_logger.start_run(query)

        try:
            # Run workflow
            result = await self.run(query=query)

            # Mark session completed
            web_logger.end_run("completed")
            return result

        except asyncio.CancelledError:
            # Handle cancellation
            web_logger.log_error(
                "Workflow has been cancelled",
                "User interrupt or system cancel",
                {"query": query, "session_id": session_id},
            )
            web_logger.end_run("cancelled")
            print("Workflow has been cancelled")
            raise

        except KeyboardInterrupt:
            # Handle keyboard interrupt
            web_logger.log_error(
                "Workflow has been interrupted",
                "User interrupt by Ctrl+C",
                {"query": query, "session_id": session_id},
            )
            web_logger.end_run("interrupted")
            print("Workflow has been interrupted by user")
            raise asyncio.CancelledError("Workflow has been interrupted by user")

        except Exception as e:
            # Record other errors and mark session failed
            web_logger.log_error(
                "Workflow execution failed", str(e), {"query": query, "session_id": session_id}
            )
            web_logger.end_run("failed")
            raise


async def main():
    """Main function, support graceful exception handling and cancellation"""
    workflow = DeepGraphWorkflow()

    try:
        result = await workflow.run_with_web_logging("金蝶国际最近半年的财务分析")
        print("Workflow execution completed:")
        print(result)

    except asyncio.CancelledError:
        print("Workflow has been cancelled")
        return

    except KeyboardInterrupt:
        print("Workflow has been interrupted by user")
        return

    except Exception as e:
        print(f"Workflow execution failed: {e}")
        return


def run_main():
    """Wrapper for running main function, handling event loop and signals"""
    import signal
    import sys

    def signal_handler(signum, frame):
        print("\nReceived interrupt signal, shutting down...")
        sys.exit(0)

    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nWorkflow has been interrupted by user")
    except Exception as e:
        print(f"\nWorkflow execution failed: {e}")
    finally:
        print("Workflow has been exited")


if __name__ == "__main__":
    import asyncio

    run_main()
