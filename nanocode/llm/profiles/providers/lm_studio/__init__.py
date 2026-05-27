from nanocode.llm.profiles import register_provider
from nanocode.llm.profiles.base import ProviderProfile

profile = ProviderProfile(
    name="lm-studio",
    aliases=("lm_studio",),
    env_vars=(),
    base_url="http://localhost:1234/v1",
    auth_type="none",
    supports_health_check=False,
)

register_provider(profile)
