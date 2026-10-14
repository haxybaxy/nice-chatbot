"""Chat routes: conversations in a team, messages that queue runs, run status / cancel, the run
event stream (SSE) and the model picker.

``/runs/active`` is registered before ``/runs/{run_id}`` so the literal path wins. Responses omit
``null`` fields (``response_model_exclude_none``): persisted message parts mirror the AI SDK UI
message shape, where absent keys are absent, so a message loaded here equals one built from the
stream — and the rest of the domain follows the same rule for consistency.
"""

from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from app.chat.dependencies import (
    CancelRunDep,
    ConversationAccessDep,
    CreateConversationDep,
    CreateMessageDep,
    DeleteConversationDep,
    GetActiveRunDep,
    GetConversationDep,
    GetRunDep,
    ListConversationsDep,
    ListModelsDep,
    RunAccessDep,
    StreamRunEventsDep,
    TeamAccessDep,
    UpdateConversationDep,
)
from app.chat.models import ConversationModel, RunModel
from app.chat.schemas import (
    ConversationDetailOut,
    ConversationOut,
    ConversationPageOut,
    CreateConversationIn,
    CreateMessageIn,
    ModelOut,
    RunOut,
    UpdateConversationIn,
)
from app.chat.use_cases.create_message import NewMessage
from app.chat.use_cases.get_conversation import ConversationDetail
from app.chat.use_cases.list_conversations import ConversationPage
from app.core.llm.catalog import ModelSpec
from app.core.openapi import error_responses
from app.core.security import CurrentUserDep
from app.core.sse import UIMessageStreamResponse

router = APIRouter(tags=["chat"], responses=error_responses(401))

_EVENT_STREAM_DESCRIPTION = (
    "AI SDK UI message stream over SSE: one JSON chunk per `data:` frame, `id:` is the run-event "
    "sequence (send it back as `Last-Event-ID` to resume), `: ping` comments keep the connection "
    "alive, and the stream ends with `data: [DONE]` after a `finish`, `error` or `abort` chunk."
)


@router.post(
    "/teams/{team_id}/conversations",
    response_model=ConversationOut,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation",
    responses=error_responses(400, 404, 422),
)
async def create_conversation(
    body: CreateConversationIn, membership: TeamAccessDep, use_case: CreateConversationDep
) -> ConversationModel:
    """With `message`, the first user message is stored and its run queued in the same transaction
    (`activeRun` is set on the response); 400 names an unknown model."""
    first = body.message
    return await use_case.execute(
        team_id=membership.team_id,
        creator=membership.user,
        title=body.title,
        visibility=body.visibility,
        message=None
        if first is None
        else NewMessage(
            texts=tuple(part.text for part in first.parts),
            model=first.model,
            mode=first.mode,
            web_search=first.tools.web_search,
            code=first.tools.code,
        ),
    )


@router.get(
    "/teams/{team_id}/conversations",
    response_model=ConversationPageOut,
    response_model_exclude_none=True,
    summary="List a team's conversations",
    responses=error_responses(400, 404, 422),
)
async def list_conversations(
    membership: TeamAccessDep,
    use_case: ListConversationsDep,
    cursor: Annotated[str | None, Query(max_length=200, description="`nextCursor` of the previous page")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ConversationPage:
    """Newest activity first; private conversations appear only to their creator. 400 on a bad cursor."""
    return await use_case.execute(team_id=membership.team_id, viewer_id=membership.user_id, cursor=cursor, limit=limit)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailOut,
    response_model_exclude_none=True,
    summary="Get a conversation with its messages",
    responses=error_responses(404, 422),
)
async def get_conversation(conversation: ConversationAccessDep, use_case: GetConversationDep) -> ConversationDetail:
    """The assistant message of a still-active run is omitted: subscribe to the run's events instead."""
    return await use_case.execute(conversation=conversation)


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationOut,
    response_model_exclude_none=True,
    summary="Update a conversation",
    responses=error_responses(403, 404, 422),
)
async def update_conversation(
    body: UpdateConversationIn,
    conversation: ConversationAccessDep,
    current_user: CurrentUserDep,
    use_case: UpdateConversationDep,
) -> ConversationModel:
    """Any reader may retitle; only the creator changes visibility (403 otherwise)."""
    return await use_case.execute(
        conversation=conversation, actor=current_user, title=body.title, visibility=body.visibility
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation",
    responses=error_responses(404, 409, 422),
)
async def delete_conversation(conversation: ConversationAccessDep, use_case: DeleteConversationDep) -> None:
    """409 while a run is active — cancel it first."""
    await use_case.execute(conversation=conversation)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=RunOut,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message",
    responses=error_responses(400, 404, 409, 422),
)
async def create_message(
    body: CreateMessageIn, conversation: ConversationAccessDep, current_user: CurrentUserDep, use_case: CreateMessageDep
) -> RunModel:
    """Stores the user message and queues the assistant's run (returned). 409 while a run is
    active in the conversation; 400 names an unknown model."""
    message = NewMessage(
        texts=tuple(part.text for part in body.parts),
        model=body.model,
        mode=body.mode,
        web_search=body.tools.web_search,
        code=body.tools.code,
    )
    return await use_case.execute(conversation_id=conversation.id, author=current_user, message=message)


@router.get(
    "/conversations/{conversation_id}/runs/active",
    response_model=RunOut,
    response_model_exclude_none=True,
    summary="Get the active run",
    responses=error_responses(404, 422),
)
async def get_active_run(conversation: ConversationAccessDep, use_case: GetActiveRunDep) -> RunModel:
    """The queued or running run of the conversation; 404 when there is none."""
    return await use_case.execute(conversation_id=conversation.id)


@router.get(
    "/conversations/{conversation_id}/runs/{run_id}",
    response_model=RunOut,
    response_model_exclude_none=True,
    summary="Get a run",
    responses=error_responses(404, 422),
)
async def get_run(run: RunAccessDep, use_case: GetRunDep) -> RunModel:
    return await use_case.execute(run_id=run.id)


@router.post(
    "/conversations/{conversation_id}/runs/{run_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a run",
    responses=error_responses(404, 422),
)
async def cancel_run(run: RunAccessDep, use_case: CancelRunDep) -> None:
    """A queued run is cancelled at once; a running one is asked to stop and ends with `abort`.
    A finished run is left alone."""
    await use_case.execute(run_id=run.id)


@router.get(
    "/conversations/{conversation_id}/runs/{run_id}/events",
    response_class=UIMessageStreamResponse,
    summary="Stream a run's events",
    responses={
        **error_responses(404, 422),
        200: {"description": _EVENT_STREAM_DESCRIPTION, "content": {"text/event-stream": {}}},
    },
)
async def stream_run_events(
    run: RunAccessDep,
    use_case: StreamRunEventsDep,
    after: Annotated[int, Query(ge=0, description="Replay events with a sequence greater than this")] = 0,
    last_event_id: Annotated[int | None, Header(ge=0, description="Takes precedence over `after`")] = None,
) -> UIMessageStreamResponse:
    """Replays the persisted events, then follows the run live until its terminal chunk."""
    start = after if last_event_id is None else last_event_id
    return UIMessageStreamResponse(use_case.execute(run_id=run.id, after=start))


@router.get(
    "/chat/models", response_model=list[ModelOut], response_model_exclude_none=True, summary="List available models"
)
async def list_models(_: CurrentUserDep, use_case: ListModelsDep) -> list[ModelSpec]:
    """The allowlisted models whose provider is configured; exactly one is the default."""
    return await use_case.execute()
