import os
from dotenv import load_dotenv
from nebula3.gclient.net import ConnectionPool
from nebula3.Config import Config

load_dotenv()

config = Config()
config.max_connection_pool_size = 10
config.timeout = 10000
config.port = os.getenv("NEBULA_PORT")
config.address = os.getenv("NEBULA_HOST")
config.user = os.getenv("NEBULA_USER")
config.password = os.getenv("NEBULA_PASSWORD")

conn = ConnectionPool()
conn.init([(config.address, config.port)], config)

session = conn.get_session(user_name=config.user, password=config.password)
session.execute("USE test_space")
