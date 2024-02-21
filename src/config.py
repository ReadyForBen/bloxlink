from typing import Literal
from os import getcwd, environ
from dotenv import load_dotenv
from pydantic import Field
from bloxlink_lib import Config as BLOXLINK_CONFIG

load_dotenv(f"{getcwd()}/.env")


class Config(BLOXLINK_CONFIG):
    """Type definition for config values."""

    #############################
    DISCORD_APPLICATION_ID: str
    DISCORD_PUBLIC_KEY: str
    BOT_RELEASE: Literal["LOCAL", "MAIN", "PRO"] = "LOCAL"
    #############################
    BIND_API_AUTH: str
    BIND_API: str
    #############################
    SERVER_HOST: str
    SERVER_PORT: int = Field(default=8010)
    HTTP_BOT_AUTH: str
    #############################


CONFIG: Config = Config(
    **{field:value for field, value in environ.items() if field in Config.model_fields}
)
