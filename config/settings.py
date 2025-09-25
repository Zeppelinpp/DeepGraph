import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    @property
    def nebula(self):
        return {
            "host": os.getenv("NEBULA_HOST"),
            "port": os.getenv("NEBULA_PORT"),
            "user": os.getenv("NEBULA_USER"),
            "password": os.getenv("NEBULA_PASSWORD"),
            "space": os.getenv("NEBULA_SPACE"),
        }

    @property
    def openai_api_key(self):
        return os.getenv("OPENAI_API_KEY")

    @property
    def openai_base_url(self):
        return os.getenv("OPENAI_BASE_URL")

    @property
    def vector_db_path(self):
        return os.getenv("VECTOR_DB_PATH")

    @property
    def agent_settigns(self):
        return {
            "planner_model": os.getenv("PLANNER_MODEL"),
            "worker_model": os.getenv("WORKER_MODEL"),
            "reviewer_model": os.getenv("REVIEWER_MODEL"),
            "summarize_model": os.getenv("SUMMARIZE_MODEL"),
        }

    @property
    def redis_host(self):
        return os.getenv("REDIS_HOST")

    @property
    def redis_port(self):
        return os.getenv("REDIS_PORT")

    @property
    def task_db(self):
        return os.getenv("TASK_DB")

    @property
    def tool_db(self):
        return os.getenv("TOOL_DB")

    @property
    def tool_cache_expiry(self):
        return os.getenv("TOOL_CACHE_EXPIRY")

    @property
    def tavily_key(self):
        return os.getenv("TAVILY_KEY")


settings = Settings()
