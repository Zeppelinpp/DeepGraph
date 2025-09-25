import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime

# Lazy import web_logger to avoid circular import
def get_web_logger():
    try:
        from src.utils.web_logger import web_logger
        return web_logger
    except ImportError:
        return None


class DeepGraphLogger:
    """Enhanced logger for DeepGraph with task and framework tracing capabilities"""
    
    def __init__(self, name: str = "DeepGraph"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Create formatter for structured logging
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Add console handler if not already present
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
    
    def log_task_tool_call(
        self, 
        task_name: str, 
        execution_type: str,  # "Sequential" or "Parallel"
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_result: str,
        duration_ms: Optional[float] = None
    ):
        """
        Log tool calls for tasks with structured format
        
        Args:
            task_name: Name of the task
            execution_type: "Sequential" or "Parallel"
            tool_name: Name of the tool being called
            tool_args: Arguments passed to the tool
            tool_result: Result returned by the tool
            duration_ms: Execution duration in milliseconds (optional)
        """
        prefix = f"[{task_name}:{execution_type}]"
        
        # Truncate long results for readability
        truncated_result = tool_result
        if len(tool_result) > 500:
            truncated_result = tool_result[:500] + "... (truncated)"
        
        # Sanitize args for logging (remove sensitive data if any)
        safe_args = self._sanitize_args(tool_args)
        
        log_data = {
            "tool_name": tool_name,
            "args": safe_args,
            "result_length": len(tool_result),
            "result_preview": truncated_result,
            "duration_ms": duration_ms
        }
        
        # Console logger
        self.logger.info(
            f"{prefix} Tool Call - {tool_name} | Args: {json.dumps(safe_args, ensure_ascii=False)} | "
            f"Result: {truncated_result} | Duration: {duration_ms}ms"
        )
        
        # Web UI logger
        web_logger = get_web_logger()
        if web_logger:
            web_logger.log_tool_call(task_name, execution_type, tool_name, tool_args, tool_result, duration_ms)
    
    def log_planner_framework_extraction(
        self,
        query: str,
        intention: str,
        framework_key: str,
        framework_content: str,
        retrieval_source: str = "analysis_frame.json"
    ):
        """
        Log planner's framework extraction for traceability
        
        Args:
            query: Original user query
            intention: Recognized intention
            framework_key: Key used to retrieve framework
            framework_content: Retrieved framework content
            retrieval_source: Source of the framework data
        """
        # Console logger
        self.logger.info(
            f"[PLANNER:Framework] Query: '{query}' | "
            f"Intention: '{intention}' | "
            f"Framework Key: '{framework_key}' | "
            f"Source: {retrieval_source} | "
            f"Framework: {framework_content[:200]}{'...' if len(framework_content) > 200 else ''}"
        )
        
        # Web UI logger
        web_logger = get_web_logger()
        if web_logger:
            web_logger.log_framework_extraction(query, intention, framework_key, framework_content, retrieval_source)
    
    def log_task_execution_start(self, task_name: str, execution_type: str, description: str):
        """Log the start of task execution"""
        prefix = f"[{task_name}:{execution_type}]"
        # Console logger
        self.logger.info(f"{prefix} Task Started - {description}")
        
        # Web UI logger
        web_logger = get_web_logger()
        if web_logger:
            web_logger.log_task_execution_start(task_name, execution_type, description)
    
    def log_task_execution_end(self, task_name: str, execution_type: str, status: str, success: bool):
        """Log the end of task execution"""
        prefix = f"[{task_name}:{execution_type}]"
        status_emoji = "✅" if success else "❌"
        # 终端日志
        self.logger.info(f"{prefix} Task Completed {status_emoji} - Status: {status} | Success: {success}")
        
        # Web UI日志
        web_logger = get_web_logger()
        if web_logger:
            web_logger.log_task_execution_end(task_name, execution_type, status, success)
    
    def log_workflow_step(self, step_name: str, event_type: str, details: str = ""):
        """Log workflow step execution"""
        # Console logger
        self.logger.info(f"[WORKFLOW:{step_name}] Event: {event_type} | {details}")
        
        # Web UI logger
        web_logger = get_web_logger()
        if web_logger:
            web_logger.log_workflow_step(step_name, event_type, details)
    
    def _sanitize_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Remove or mask sensitive information from arguments"""
        sanitized = {}
        sensitive_keys = ['password', 'token', 'key', 'secret', 'api_key']
        
        for key, value in args.items():
            if any(sensitive_key in key.lower() for sensitive_key in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, str) and len(value) > 1000:
                sanitized[key] = value[:1000] + "... (truncated)"
            else:
                sanitized[key] = value
        
        return sanitized


# Global logger instance
logger = DeepGraphLogger()

# Maintain backward compatibility
def get_logger() -> DeepGraphLogger:
    """Get the global DeepGraph logger instance"""
    return logger