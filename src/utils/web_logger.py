import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import weakref


class LogLevel(str, Enum):
    """日志级别"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class LogType(str, Enum):
    """日志类型"""

    WORKFLOW = "workflow"
    TASK = "task"
    TOOL_CALL = "tool_call"
    FRAMEWORK = "framework"
    SYSTEM = "system"


@dataclass
class ToolCall:
    """工具调用记录"""

    id: str
    tool_name: str
    tool_args: Dict[str, Any]
    tool_result: str
    duration_ms: Optional[float] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": self.tool_result,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TaskEntry:
    """任务条目"""

    id: str
    name: str
    execution_type: str  # "Sequential" or "Parallel"
    description: str
    status: str = "pending"  # pending, running, completed, failed
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    tool_calls: List[ToolCall] = None
    result: Optional[str] = None
    success: Optional[bool] = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []

    @property
    def duration_ms(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "execution_type": self.execution_type,
            "description": self.description,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "result": self.result,
            "success": self.success,
        }


@dataclass
class LogEntry:
    """单个日志条目"""

    id: str
    timestamp: datetime
    level: LogLevel
    type: LogType
    title: str
    content: str
    details: Optional[Dict[str, Any]] = None
    duration_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class RunSession:
    """运行会话"""

    id: str
    query: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "running"  # running, completed, failed
    logs: List[LogEntry] = None
    tasks: Dict[str, TaskEntry] = None  # task_name -> TaskEntry

    def __post_init__(self):
        if self.logs is None:
            self.logs = []
        if self.tasks is None:
            self.tasks = {}

    @property
    def duration_ms(self) -> Optional[float]:
        """会话持续时间（毫秒）"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    @property
    def sequential_tasks(self) -> List[TaskEntry]:
        """获取顺序任务"""
        return [
            task for task in self.tasks.values() if task.execution_type == "Sequential"
        ]

    @property
    def parallel_tasks(self) -> List[TaskEntry]:
        """获取并行任务"""
        return [
            task for task in self.tasks.values() if task.execution_type == "Parallel"
        ]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "id": self.id,
            "query": self.query,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "log_count": len(self.logs),
            "task_count": len(self.tasks),
            "sequential_tasks": [task.to_dict() for task in self.sequential_tasks],
            "parallel_tasks": [task.to_dict() for task in self.parallel_tasks],
            "logs": [log.to_dict() for log in self.logs],
        }


class WebLogManager:
    """Web UI日志管理器"""

    def __init__(self, max_sessions: int = 100):
        self.max_sessions = max_sessions
        self.sessions: Dict[str, RunSession] = {}
        self.current_session_id: Optional[str] = None
        self.websocket_connections: weakref.WeakSet = weakref.WeakSet()

    def start_session(self, query: str) -> str:
        """开始新的运行会话"""
        session_id = str(uuid.uuid4())[:8]
        session = RunSession(id=session_id, query=query, start_time=datetime.now())

        # 保持会话数量在限制内
        if len(self.sessions) >= self.max_sessions:
            oldest_session = min(self.sessions.values(), key=lambda s: s.start_time)
            del self.sessions[oldest_session.id]

        self.sessions[session_id] = session
        self.current_session_id = session_id

        # 广播新会话开始
        self._broadcast_update({"type": "session_start", "session": session.to_dict()})

        return session_id

    def end_session(self, status: str = "completed"):
        """结束当前会话"""
        if self.current_session_id and self.current_session_id in self.sessions:
            session = self.sessions[self.current_session_id]
            session.end_time = datetime.now()
            session.status = status

            # 广播会话结束
            self._broadcast_update(
                {"type": "session_end", "session": session.to_dict()}
            )

            self.current_session_id = None

    def add_log(
        self,
        level: LogLevel,
        log_type: LogType,
        title: str,
        content: str,
        details: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ):
        """添加日志条目"""
        if not self.current_session_id:
            return

        session = self.sessions.get(self.current_session_id)
        if not session:
            return

        log_entry = LogEntry(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(),
            level=level,
            type=log_type,
            title=title,
            content=content,
            details=details,
            duration_ms=duration_ms,
        )

        session.logs.append(log_entry)

        # 广播新日志
        self._broadcast_update(
            {
                "type": "new_log",
                "session_id": self.current_session_id,
                "log": log_entry.to_dict(),
            }
        )

    def get_sessions(self) -> List[Dict[str, Any]]:
        """获取所有会话"""
        return [
            session.to_dict()
            for session in sorted(
                self.sessions.values(), key=lambda s: s.start_time, reverse=True
            )
        ]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取特定会话"""
        session = self.sessions.get(session_id)
        return session.to_dict() if session else None

    def add_websocket(self, websocket):
        """添加WebSocket连接"""
        self.websocket_connections.add(websocket)

    def remove_websocket(self, websocket):
        """移除WebSocket连接"""
        self.websocket_connections.discard(websocket)

    def _broadcast_update(self, message: Dict[str, Any]):
        """广播更新到所有WebSocket连接"""
        if not self.websocket_connections:
            return

        message_str = json.dumps(message, ensure_ascii=False)

        # 异步发送到所有连接
        asyncio.create_task(self._send_to_all_websockets(message_str))

    async def _send_to_all_websockets(self, message: str):
        """发送消息到所有WebSocket连接"""
        if not self.websocket_connections:
            return

        # 创建发送任务列表
        tasks = []
        for ws in list(self.websocket_connections):
            try:
                tasks.append(ws.send_text(message))
            except Exception:
                # 连接已断开，会被WeakSet自动清理
                pass

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# 全局Web日志管理器实例
web_log_manager = WebLogManager()


class WebUILogger:
    """Web UI日志记录器"""

    def __init__(self, manager: WebLogManager = None):
        self.manager = manager or web_log_manager

    def start_run(self, query: str) -> str:
        """开始运行会话"""
        return self.manager.start_session(query)

    def end_run(self, status: str = "completed"):
        """结束运行会话"""
        self.manager.end_session(status)

    def get_or_create_task(
        self, task_name: str, execution_type: str, description: str
    ) -> TaskEntry:
        """获取或创建任务条目"""
        if not self.manager.current_session_id:
            return None

        session = self.manager.sessions.get(self.manager.current_session_id)
        if not session:
            return None

        if task_name not in session.tasks:
            task_entry = TaskEntry(
                id=str(uuid.uuid4())[:8],
                name=task_name,
                execution_type=execution_type,
                description=description,
            )
            session.tasks[task_name] = task_entry

            # 广播新任务
            self.manager._broadcast_update(
                {
                    "type": "task_created",
                    "session_id": self.manager.current_session_id,
                    "task": task_entry.to_dict(),
                }
            )

        return session.tasks[task_name]

    def log_workflow_step(self, step_name: str, event_type: str, details: str = ""):
        """记录工作流步骤"""
        self.manager.add_log(
            level=LogLevel.INFO,
            log_type=LogType.WORKFLOW,
            title=f"工作流: {step_name}",
            content=f"事件: {event_type}",
            details={"step": step_name, "event": event_type, "details": details},
        )

    def log_task_execution_start(
        self, task_name: str, execution_type: str, description: str
    ):
        """记录任务开始执行"""
        # 创建或获取任务条目
        task_entry = self.get_or_create_task(task_name, execution_type, description)
        if task_entry:
            task_entry.status = "running"
            task_entry.start_time = datetime.now()

            # 广播任务状态更新
            self.manager._broadcast_update(
                {
                    "type": "task_updated",
                    "session_id": self.manager.current_session_id,
                    "task": task_entry.to_dict(),
                }
            )

        # 保留原有的日志记录
        self.manager.add_log(
            level=LogLevel.INFO,
            log_type=LogType.TASK,
            title=f"任务开始: {task_name}",
            content=f"[{execution_type}] {description}",
            details={
                "task_name": task_name,
                "execution_type": execution_type,
                "description": description,
                "action": "start",
            },
        )

    def log_task_execution_end(
        self, task_name: str, execution_type: str, status: str, success: bool
    ):
        """记录任务执行结束"""
        # 更新任务条目
        if self.manager.current_session_id:
            session = self.manager.sessions.get(self.manager.current_session_id)
            if session and task_name in session.tasks:
                task_entry = session.tasks[task_name]
                task_entry.status = status
                task_entry.success = success
                task_entry.end_time = datetime.now()

                # 广播任务状态更新
                self.manager._broadcast_update(
                    {
                        "type": "task_updated",
                        "session_id": self.manager.current_session_id,
                        "task": task_entry.to_dict(),
                    }
                )

        level = LogLevel.SUCCESS if success else LogLevel.ERROR
        status_emoji = "✅" if success else "❌"

        self.manager.add_log(
            level=level,
            log_type=LogType.TASK,
            title=f"任务完成: {task_name}",
            content=f"[{execution_type}] {status_emoji} {status}",
            details={
                "task_name": task_name,
                "execution_type": execution_type,
                "status": status,
                "success": success,
                "action": "end",
            },
        )

    def log_tool_call(
        self,
        task_name: str,
        execution_type: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_result: str,
        duration_ms: Optional[float] = None,
    ):
        """记录工具调用"""
        # 添加工具调用到任务
        if self.manager.current_session_id:
            session = self.manager.sessions.get(self.manager.current_session_id)
            if session and task_name in session.tasks:
                task_entry = session.tasks[task_name]
                tool_call = ToolCall(
                    id=str(uuid.uuid4())[:8],
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                    duration_ms=duration_ms,
                )
                task_entry.tool_calls.append(tool_call)

                # 广播工具调用更新
                self.manager._broadcast_update(
                    {
                        "type": "tool_call_added",
                        "session_id": self.manager.current_session_id,
                        "task_name": task_name,
                        "tool_call": tool_call.to_dict(),
                    }
                )

        # 截断长结果用于日志显示
        truncated_result = tool_result
        if len(tool_result) > 200:
            truncated_result = tool_result[:200] + "..."

        self.manager.add_log(
            level=LogLevel.INFO,
            log_type=LogType.TOOL_CALL,
            title=f"工具调用: {tool_name}",
            content=f"[{task_name}:{execution_type}] {truncated_result}",
            details={
                "task_name": task_name,
                "execution_type": execution_type,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "result_length": len(tool_result),
                "full_result": tool_result,
            },
            duration_ms=duration_ms,
        )

    def log_framework_extraction(
        self,
        query: str,
        intention: str,
        framework_key: str,
        framework_content: str,
        retrieval_source: str = "analysis_frame.json",
    ):
        """记录框架提取"""
        self.manager.add_log(
            level=LogLevel.INFO,
            log_type=LogType.FRAMEWORK,
            title="框架提取",
            content=f"意图: {intention} → 框架: {framework_key}",
            details={
                "query": query,
                "intention": intention,
                "framework_key": framework_key,
                "framework_content": framework_content,
                "retrieval_source": retrieval_source,
            },
        )

    def log_error(
        self, title: str, error: str, details: Optional[Dict[str, Any]] = None
    ):
        """记录错误"""
        self.manager.add_log(
            level=LogLevel.ERROR,
            log_type=LogType.SYSTEM,
            title=f"错误: {title}",
            content=error,
            details=details,
        )


# 全局Web UI日志记录器实例
web_logger = WebUILogger()
