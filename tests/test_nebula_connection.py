import os
from dotenv import load_dotenv
from nebula3.gclient.net import ConnectionPool
from nebula3.Config import Config
from config.settings import settings

load_dotenv()

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
result = session.execute("SHOW EDGES").as_primitive()
print(result)
