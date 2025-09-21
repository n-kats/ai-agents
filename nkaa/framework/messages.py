from nkaa.framework.agent import BaseMessage


class StopMessage(BaseMessage):
    """
    A message to stop the agent.
    This message is used to signal the agent to stop processing and exit gracefully.
    """

    def __init__(self, created_at: datetime = None):
        super().__init__(created_at=created_at)


class SystemMessage(BaseMessage):
    pass


class AgentToChannelMessage(BaseMessage):
    """
    A message to send to a channel agent.
    This message is used to communicate with channel agents.
    """

    def __init__(self, agent_id_from: str, channel_id_to: str, content, created_at: datetime = None):
        super().__init__(created_at=created_at)
        self.__agent_id_from = agent_id_from
        self.__channel_id_to = channel_id_to
        self.__content = content

    @property
    def channel_id_to(self) -> str:
        return self.__channel_id_to

    @property
    def agent_id_from(self) -> str:
        return self.__agent_id_from


class ChannelToAgentMessage(BaseMessage):
    """
    A message to send to a task agent.
    This message is used to communicate with task agents.
    """

    def __init__(self, channel_id_from: str, agent_id_to: str, created_at: datetime = None):
        super().__init__(created_at=created_at)
        self.__channel_id_from = channel_id_from
        self.__agent_id_to = agent_id_to

    @property
    def channel_id_from(self) -> str:
        return self.__channel_id_from

    @property
    def agent_id_to(self) -> str:
        return self.__agent_id_to


class ChannelSearchMessage(BaseMessage):
    pass


class ChannelJoinMessage(BaseMessage):
    pass


class ChannelLeaveMessage(BaseMessage):
    pass


class GetChannelInfoMessage(BaseMessage):
    pass


class ChannelInfoMessage(BaseMessage):
    pass


class BroadcastMessage(BaseMessage):
    pass


class MenssionMessage(BaseMessage):
    pass


class CreateChannelMessage(BaseMessage):
    pass


class CreateAgentMessage(BaseMessage):
    pass


class CloseAgentMessage(BaseMessage):
    pass


class SuccessMessage(BaseMessage):
    pass


class ErrorMessage(BaseMessage):
    pass


class RefuseMessage(BaseMessage):
    pass


class ChannelCloseMessage(BaseMessage):
    pass


class ChannelClosingMessage(BaseMessage):
    pass


class ChannelClosedMessage(BaseMessage):
    pass
