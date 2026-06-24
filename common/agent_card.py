"""A2A AgentCard(protobuf) 생성 책임."""
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill


def build_agent_card(
    name: str,
    description: str,
    url: str,
    skill_id: str,
    skill_name: str,
    skill_description: str,
    skill_tags: list[str],
) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url)
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id=skill_id,
                name=skill_name,
                description=skill_description,
                tags=skill_tags,
            )
        ],
    )
