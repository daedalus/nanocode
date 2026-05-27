from nanocode.llm.profiles import register_provider
from nanocode.llm.profiles.base import ProviderProfile

profile = ProviderProfile(
    name="ollama",
    aliases=("local",),
    env_vars=(),
    base_url="http://localhost:11434",
    auth_type="none",
    supports_health_check=False,
    default_aux_model="",
)

register_provider(profile)
