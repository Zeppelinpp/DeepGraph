from nebula3.Config import Config
from nebula3.gclient.net import ConnectionPool
from config.settings import settings
from typing import Any


def execute_ngql(ngql: str) -> Any:
    """
    Execute nGQL query and return result
    """
    config = Config()
    config.max_connection_pool_size = 10
    config.timeout = 10000
    config.port = settings.nebula["port"]
    config.address = settings.nebula["host"]
    config.user = settings.nebula["user"]
    config.password = settings.nebula["password"]

    conn = ConnectionPool()
    conn.init([(config.address, config.port)], config)

    session = conn.get_session(user_name=config.user, password=config.password)
    session.execute(f"USE {settings.nebula['space']}")

    ngql = ngql.strip()
    if ngql.startswith("```"):
        ngql = ngql.strip("```sql\n").strip("```").strip()

    result = session.execute(ngql).as_primitive()
    return result