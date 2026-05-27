from nanocode.llm.profiles import register_provider
from nanocode.llm.profiles.base import ProviderProfile

profile = ProviderProfile(
    name="openai",
    aliases=("openai-compatible",),
    env_vars=("OPENAI_API_KEY",),
    base_url="https://api.openai.com/v1",
    fallback_models=(
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        "o1",
        "o3-mini",
    ),
    default_aux_model="gpt-4o-mini",
)

register_provider(profile)
