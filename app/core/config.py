from pydantic_settings import BaseSettings, SettingsConfigDict

"""We never want to read os.getenv() randomly throughout our code. 
We will use Pydantic's BaseSettings to load and validate our .env variables right when the app starts."""

class Settings(BaseSettings):
    PROJECT_NAME: str = "Distributed Chat Stage 2"
    VERSION: str = "2.0.0"

    SERVER_ID: str = "chat-server-local"
    REDIS_URL: str = "redis://localhost:6379/0"
    RABBITMQ_URL: str = "amqp://admin:admin@localhost/"
    MESSAGE_ENCRYPTION_KEY: str 

    # Database
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    DATABASE_URL: str
    SYNC_DATABASE_URL: str

    # Security
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()