"""FastAPI dependencies for the chat domain.

Access is resolved from the path and checked here so the use cases only see objects the caller
may touch: ``get_team_access`` (team member, else 404), ``get_conversation_access`` (team member
*and* the conversation is visible to them, else 404 — a non-member can't tell whether it exists)
and ``get_run_access`` (a run of that conversation, else 404). Team membership comes from the
teams domain's public ``FindTeamMembership`` use case.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.chat.models import ConversationModel, ConversationVisibility, RunModel
from app.chat.repository import ConversationRepository, RunRepository
from app.chat.use_cases.cancel_run import CancelRun
from app.chat.use_cases.create_conversation import CreateConversation
from app.chat.use_cases.create_message import CreateMessage
from app.chat.use_cases.delete_conversation import DeleteConversation
from app.chat.use_cases.get_active_run import GetActiveRun
from app.chat.use_cases.get_conversation import GetConversation
from app.chat.use_cases.get_run import GetRun
from app.chat.use_cases.list_conversations import ListConversations
from app.chat.use_cases.list_models import ListModels
from app.chat.use_cases.stream_run_events import StreamRunEvents
from app.chat.use_cases.update_conversation import UpdateConversation
from app.core.exceptions import AppError
from app.core.security import CurrentUserDep
from app.db.listen import ListenerDep
from app.db.session import DbDep, SessionScopeDep
from app.teams.models import TeamMemberModel
from app.teams.use_cases.find_team_membership import FindTeamMembership


async def get_team_access(team_id: UUID, current_user: CurrentUserDep, db: DbDep) -> TeamMemberModel:
    membership = await FindTeamMembership(db).execute(team_id=team_id, user_id=current_user.id)
    if membership is None:
        raise AppError.not_found("Team", team_id)
    return membership


TeamAccessDep = Annotated[TeamMemberModel, Depends(get_team_access)]


async def get_conversation_access(conversation_id: UUID, current_user: CurrentUserDep, db: DbDep) -> ConversationModel:
    conversation = await ConversationRepository(db).get_by_id(conversation_id)
    if conversation is None:
        raise AppError.not_found("Conversation", conversation_id)
    membership = await FindTeamMembership(db).execute(team_id=conversation.team_id, user_id=current_user.id)
    is_private = conversation.visibility == ConversationVisibility.PRIVATE.value
    if membership is None or (is_private and conversation.created_by != current_user.id):
        raise AppError.not_found("Conversation", conversation_id)
    return conversation


ConversationAccessDep = Annotated[ConversationModel, Depends(get_conversation_access)]


async def get_run_access(run_id: UUID, conversation: ConversationAccessDep, db: DbDep) -> RunModel:
    run = await RunRepository(db).get_by_id(run_id)
    if run is None or run.conversation_id != conversation.id:
        raise AppError.not_found("Run", run_id)
    return run


RunAccessDep = Annotated[RunModel, Depends(get_run_access)]


async def create_conversation_use_case(db: DbDep) -> CreateConversation:
    return CreateConversation(db)


async def list_conversations_use_case(db: DbDep) -> ListConversations:
    return ListConversations(db)


async def get_conversation_use_case(db: DbDep) -> GetConversation:
    return GetConversation(db)


async def update_conversation_use_case(db: DbDep) -> UpdateConversation:
    return UpdateConversation(db)


async def delete_conversation_use_case(db: DbDep) -> DeleteConversation:
    return DeleteConversation(db)


async def create_message_use_case(db: DbDep) -> CreateMessage:
    return CreateMessage(db)


async def get_active_run_use_case(db: DbDep) -> GetActiveRun:
    return GetActiveRun(db)


async def get_run_use_case(db: DbDep) -> GetRun:
    return GetRun(db)


async def cancel_run_use_case(db: DbDep) -> CancelRun:
    return CancelRun(db)


async def stream_run_events_use_case(sessions: SessionScopeDep, listener: ListenerDep) -> StreamRunEvents:
    # No request session: the stream outlives the request transaction and reads in short scopes.
    return StreamRunEvents(sessions, listener)


async def list_models_use_case() -> ListModels:
    return ListModels()


CreateConversationDep = Annotated[CreateConversation, Depends(create_conversation_use_case)]
ListConversationsDep = Annotated[ListConversations, Depends(list_conversations_use_case)]
GetConversationDep = Annotated[GetConversation, Depends(get_conversation_use_case)]
UpdateConversationDep = Annotated[UpdateConversation, Depends(update_conversation_use_case)]
DeleteConversationDep = Annotated[DeleteConversation, Depends(delete_conversation_use_case)]
CreateMessageDep = Annotated[CreateMessage, Depends(create_message_use_case)]
GetActiveRunDep = Annotated[GetActiveRun, Depends(get_active_run_use_case)]
GetRunDep = Annotated[GetRun, Depends(get_run_use_case)]
CancelRunDep = Annotated[CancelRun, Depends(cancel_run_use_case)]
StreamRunEventsDep = Annotated[StreamRunEvents, Depends(stream_run_events_use_case)]
ListModelsDep = Annotated[ListModels, Depends(list_models_use_case)]
