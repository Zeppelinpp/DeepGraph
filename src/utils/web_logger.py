import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import weakref


class LogLevel(str, Enum):
    """Log levels"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class LogType(str, Enum):
    """Log types"""

    WORKFLOW = "workflow"
    TASK = "task"
    TOOL_CALL = "tool_call"
    FRAMEWORK = "framework"
    SYSTEM = "system"


@dataclass
class ToolCall:
    """Tool call record"""

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
    """Task entry"""

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
    """Single log entry"""

    id: str
    timestamp: datetime
    level: LogLevel
    type: LogType
    title: str
    content: str
    details: Optional[Dict[str, Any]] = None
    duration_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class RunSession:
    """Run session"""

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
        """Session duration (milliseconds)"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    @property
    def sequential_tasks(self) -> List[TaskEntry]:
        """Get sequential tasks"""
        return [
            task for task in self.tasks.values() if task.execution_type == "Sequential"
        ]

    @property
    def parallel_tasks(self) -> List[TaskEntry]:
        """Get parallel tasks"""
        return [
            task for task in self.tasks.values() if task.execution_type == "Parallel"
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
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
    """Web UI logger manager"""

    def __init__(self, max_sessions: int = 100):
        self.max_sessions = max_sessions
        self.sessions: Dict[str, RunSession] = {}
        self.current_session_id: Optional[str] = None
        self.websocket_connections: weakref.WeakSet = weakref.WeakSet()

    def start_session(self, query: str) -> str:
        """Start new run session"""
        session_id = str(uuid.uuid4())[:8]
        session = RunSession(id=session_id, query=query, start_time=datetime.now())

        # Keep session count within limit
        if len(self.sessions) >= self.max_sessions:
            oldest_session = min(self.sessions.values(), key=lambda s: s.start_time)
            del self.sessions[oldest_session.id]

        self.sessions[session_id] = session
        self.current_session_id = session_id

        # Broadcast new session start
        self._broadcast_update({"type": "session_start", "session": session.to_dict()})

        return session_id

    def end_session(self, status: str = "completed"):
        """End current session"""
        if self.current_session_id and self.current_session_id in self.sessions:
            session = self.sessions[self.current_session_id]
            session.end_time = datetime.now()
            session.status = status

            # Broadcast session end
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
        """Add log entry"""
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

        # Broadcast new log
        self._broadcast_update(
            {
                "type": "new_log",
                "session_id": self.current_session_id,
                "log": log_entry.to_dict(),
            }
        )

    def get_sessions(self) -> List[Dict[str, Any]]:
        """Get all sessions"""
        return [
            session.to_dict()
            for session in sorted(
                self.sessions.values(), key=lambda s: s.start_time, reverse=True
            )
        ]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get specific session"""
        session = self.sessions.get(session_id)
        return session.to_dict() if session else None

    def add_websocket(self, websocket):
        """Add WebSocket connection"""
        self.websocket_connections.add(websocket)

    def remove_websocket(self, websocket):
        """Remove WebSocket connection"""
        self.websocket_connections.discard(websocket)

    def _broadcast_update(self, message: Dict[str, Any]):
        """Broadcast update to all WebSocket connections"""
        if not self.websocket_connections:
            return

        message_str = json.dumps(message, ensure_ascii=False)

        # Async send to all connections
        asyncio.create_task(self._send_to_all_websockets(message_str))

    async def _send_to_all_websockets(self, message: str):
        """Send message to all WebSocket connections"""
        if not self.websocket_connections:
            return

        # Create send task list
        tasks = []
        for ws in list(self.websocket_connections):
            try:
                tasks.append(ws.send_text(message))
            except Exception:
                # Connection is disconnected, will be automatically cleaned by WeakSet
                pass

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# Global Web log manager instance
web_log_manager = WebLogManager()


class WebUILogger:
    """Web UI logger"""

    def __init__(self, manager: WebLogManager = None):
        self.manager = manager or web_log_manager

    def start_run(self, query: str) -> str:
        """Start running session"""
        return self.manager.start_session(query)

    def end_run(self, status: str = "completed"):
        """End running session"""
        self.manager.end_session(status)

    def get_or_create_task(
        self, task_name: str, execution_type: str, description: str
    ) -> TaskEntry:
        """Get or create task entry"""
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

            # Broadcast new task
            self.manager._broadcast_update(
                {
                    "type": "task_created",
                    "session_id": self.manager.current_session_id,
                    "task": task_entry.to_dict(),
                }
            )

        return session.tasks[task_name]

    def log_workflow_step(self, step_name: str, event_type: str, details: str = ""):
        """Log workflow step"""
        self.manager.add_log(
            level=LogLevel.INFO,
            log_type=LogType.WORKFLOW,
            title=f"Workflow: {step_name}",
            content=f"Event: {event_type}",
            details={"step": step_name, "event": event_type, "details": details},
        )

    def log_task_execution_start(
        self, task_name: str, execution_type: str, description: str
    ):
        """Log task execution start"""
        # Create or get task entry
        task_entry = self.get_or_create_task(task_name, execution_type, description)
        if task_entry:
            task_entry.status = "running"
            task_entry.start_time = datetime.now()

            # Broadcast task status update
            self.manager._broadcast_update(
                {
                    "type": "task_updated",
                    "session_id": self.manager.current_session_id,
                    "task": task_entry.to_dict(),
                }
            )

        # Keep original log record
        self.manager.add_log(
            level=LogLevel.INFO,
            log_type=LogType.TASK,
            title=f"Task Start: {task_name}",
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
        """Log task execution end"""
        # Update task entry
        if self.manager.current_session_id:
            session = self.manager.sessions.get(self.manager.current_session_id)
            if session and task_name in session.tasks:
                task_entry = session.tasks[task_name]
                task_entry.status = status
                task_entry.success = success
                task_entry.end_time = datetime.now()

                # Broadcast task status update
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
            title=f"Task Completed: {task_name}",
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
        """Log tool call"""
        # Add tool call to task
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

                # Broadcast tool call update
                self.manager._broadcast_update(
                    {
                        "type": "tool_call_added",
                        "session_id": self.manager.current_session_id,
                        "task_name": task_name,
                        "tool_call": tool_call.to_dict(),
                    }
                )

        # Truncate long result for logging display
        truncated_result = tool_result
        if len(tool_result) > 200:
            truncated_result = tool_result[:200] + "..."

        self.manager.add_log(
            level=LogLevel.INFO,
            log_type=LogType.TOOL_CALL,
            title=f"Tool Call: {tool_name}",
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
        """Log framework extraction"""
        self.manager.add_log(
            level=LogLevel.INFO,
            log_type=LogType.FRAMEWORK,
            title="Framework Extraction",
            content=f"Intention: {intention} → Framework: {framework_key}",
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
        """Log error"""
        self.manager.add_log(
            level=LogLevel.ERROR,
            log_type=LogType.SYSTEM,
            title=f"Error: {title}",
            content=error,
            details=details,
        )


# Global Web UI logger instance
web_logger = WebUILogger()
