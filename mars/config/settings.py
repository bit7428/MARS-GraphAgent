"""配置层：环境变量读取与节点级 LLM 配置。"""

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NodeLLMConfig(BaseModel):
    """单个 LLM 节点的运行配置；密钥只保存环境变量名。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    base_url: str | None = None
    api_key_env: str
    temperature: float = 0.2
    timeout_s: float = 60.0
    max_retries: int = 2
    prompt_version: str = "v1"


class NodeOverride(BaseModel):
    """节点配置覆盖项，None 表示沿用默认值。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float | None = None
    timeout_s: float | None = None
    max_retries: int | None = None
    prompt_version: str | None = None


class Settings(BaseSettings):
    """进程级配置，全部来自 MARS_ 前缀环境变量。"""

    model_config = SettingsConfigDict(env_prefix="MARS_", extra="ignore", frozen=True)

    default_model: str = "deepseek-chat"
    base_url: str | None = "https://api.deepseek.com/v1"
    api_key_env: str = "MARS_LLM_API_KEY"
    temperature: float = 0.2
    timeout_s: float = 60.0
    max_retries: int = 2
    prompt_version: str = "v1"
    node_configs: dict[str, NodeOverride] = Field(default_factory=dict)

    def base_node_config(self) -> NodeLLMConfig:
        """由全局默认值构造节点配置。"""
        return NodeLLMConfig(
            model=self.default_model,
            base_url=self.base_url,
            api_key_env=self.api_key_env,
            temperature=self.temperature,
            timeout_s=self.timeout_s,
            max_retries=self.max_retries,
            prompt_version=self.prompt_version,
        )

    def node_config(self, node: str) -> NodeLLMConfig:
        """按节点名返回默认配置与覆盖合并结果。"""
        return _merge_override(self.base_node_config(), self.node_configs.get(node))


def _merge_override(base: NodeLLMConfig, override: NodeOverride | None) -> NodeLLMConfig:
    if override is None:
        return base
    changes = {key: value for key, value in override.model_dump().items() if value is not None}
    return base.model_copy(update=changes)


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """缓存不可变配置，避免每次节点执行重复读环境变量。"""
    return Settings()


def default_node_config(node: str) -> NodeLLMConfig:
    """按节点名读取环境配置；未单独配置的节点共用默认值。"""
    settings = load_settings()
    return _merge_override(settings.base_node_config(), settings.node_configs.get(node))


class NodeConfigStore:
    """进程内节点配置覆盖（API 可修改），不落盘、不保存密钥。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or load_settings()
        self._overrides: dict[str, NodeOverride] = {}

    def node_config(self, node: str) -> NodeLLMConfig:
        """返回进程内覆盖后的节点配置。"""
        base = self._settings.node_config(node)
        return _merge_override(base, self._overrides.get(node))

    def snapshot(self) -> dict[str, NodeLLMConfig]:
        """快照全部节点配置，供单次运行固定使用。"""
        from mars.graph.state.constants import NODE_NAMES

        return {node: self.node_config(node) for node in NODE_NAMES}

    def update(self, node: str, override: NodeOverride) -> NodeLLMConfig:
        """更新节点覆盖配置。"""
        self._overrides[node] = override
        return self.node_config(node)

    def reset(self, node: str) -> NodeLLMConfig:
        """清除节点覆盖配置。"""
        self._overrides.pop(node, None)
        return self.node_config(node)
