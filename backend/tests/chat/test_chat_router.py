"""HTTP tests for the chat API: conversations, messages, runs, the SSE event stream and models."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import (
    ConversationModel,
    ConversationVisibility,
    MessageModel,
    MessageRole,
    RunEventModel,
    RunModel,
    RunStatus,
)
from app.chat.use_cases.stream_run_events import StreamRunEvents
from app.core.config import chat_settings
from app.core.sse import SSE_PING, UI_MESSAGE_STREAM_HEADER
from app.core.ui_stream import JsonObject
from app.db.session import SessionScope
from app.organizations.models import OrganizationModel, OrganizationRole
from app.teams.models import TeamModel
from app.users.models import UserModel
from tests.core.test_ui_stream import CANONICAL
from tests.fakes import FakeListener
from tests.seeds import (
    seed_conversation,
    seed_member,
    seed_message,
    seed_organization,
    seed_run,
    seed_run_events,
    seed_team,
    seed_team_member,
    seed_user,
)

type Authenticate = Callable[[UserModel], None]

TEXT = {"type": "text", "text": "What changed in Python 3.14?"}


@dataclass
class Stream:
    """A parsed SSE body: ``(id, chunk)`` frames, comment pings, and whether ``[DONE]`` closed it."""

    frames: list[tuple[int, object]] = field(default_factory=list)
    pings: int = 0
    done: bool = False

    @property
    def ids(self) -> list[int]:
        return [seq for seq, _ in self.frames]

    @property
    def chunks(self) -> list[object]:
        return [chunk for _, chunk in self.frames]


def _parse(lines: list[str]) -> Stream:
    stream = Stream()
    current_id: int | None = None
    for line in lines:
        if line == ": ping":
            stream.pings += 1
        elif line.startswith("id: "):
            current_id = int(line.removeprefix("id: "))
        elif line == "data: [DONE]":
            stream.done = True
        elif line.startswith("data: "):
            assert current_id is not None, "every data frame carries an id"
            stream.frames.append((current_id, json.loads(line.removeprefix("data: "))))
            current_id = None
    return stream


async def _read_stream(response: Response) -> Stream:
    assert response.status_code == 200, await response.aread()
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers[UI_MESSAGE_STREAM_HEADER] == "v1"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    return _parse([line async for line in response.aiter_lines()])


async def _messages(db: AsyncSession, conversation_id: UUID) -> list[MessageModel]:
    result = await db.execute(
        select(MessageModel).where(MessageModel.conversation_id == conversation_id).order_by(MessageModel.position)
    )
    return list(result.scalars())


async def _events(db: AsyncSession, run_id: UUID) -> list[RunEventModel]:
    result = await db.execute(select(RunEventModel).where(RunEventModel.run_id == run_id).order_by(RunEventModel.seq))
    return list(result.scalars())


@pytest.fixture
async def owner(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="owner@example.com", full_name="Org Owner")


@pytest.fixture
async def organization(db_session: AsyncSession, owner: UserModel) -> OrganizationModel:
    return await seed_organization(db_session, name="Nice Chatbot", owner=owner)


@pytest.fixture
async def team(db_session: AsyncSession, organization: OrganizationModel, owner: UserModel) -> TeamModel:
    return await seed_team(db_session, organization=organization, name="Research", creator=owner)


@pytest.fixture
async def member(db_session: AsyncSession, organization: OrganizationModel, team: TeamModel) -> UserModel:
    user = await seed_user(db_session, email="member@example.com", full_name="Team Member")
    await seed_member(db_session, organization, user, OrganizationRole.MEMBER)
    await seed_team_member(db_session, team, user)
    return user


@pytest.fixture
async def outsider(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="outsider@example.com")


@pytest.fixture
async def conversation(db_session: AsyncSession, team: TeamModel, owner: UserModel) -> ConversationModel:
    conversation = await seed_conversation(db_session, team=team, creator=owner, title="Python 3.14")
    await seed_message(db_session, conversation=conversation, role=MessageRole.USER, position=0, created_by=owner)
    return conversation


class TestCreateConversation:
    async def test_first_message_is_stored_and_its_run_queued(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(owner)

        response = await client.post(
            f"/api/teams/{team.id}/conversations",
            json={"title": "Hello", "message": {"parts": [TEXT], "tools": {"code": True}}},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"] == "Hello"
        assert body["visibility"] == "team"
        assert body["createdBy"] == str(owner.id)
        assert body["model"] == "anthropic:claude-opus-5-5"
        run = body["activeRun"]
        assert run["status"] == "queued"
        assert run["mode"] == "chat"
        assert run["model"] == "anthropic:claude-opus-5-5"
        assert run["provider"] == "anthropic"
        assert run["effort"] == "medium"
        assert run["options"] == {"webSearch": True, "code": True}
        assert (run["attempt"], run["lastSeq"], run.get("traceId"), run.get("error")) == (1, 0, None, None)
        messages = await _messages(db_session, UUID(body["id"]))
        assert [(m.role, m.position, m.parts, m.created_by) for m in messages] == [("user", 0, [TEXT], owner.id)]
        stored_run = await db_session.get(RunModel, UUID(run["id"]))
        assert stored_run is not None
        assert (stored_run.status, stored_run.requested_by, stored_run.trace_id) == ("queued", owner.id, None)

    async def test_private_conversation_without_message(
        self, client: AsyncClient, team: TeamModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.post(f"/api/teams/{team.id}/conversations", json={"visibility": "private"})

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["visibility"] == "private"
        assert "title" not in body  # null fields are omitted
        assert "activeRun" not in body

    async def test_unknown_model_is_400(
        self, client: AsyncClient, team: TeamModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.post(
            f"/api/teams/{team.id}/conversations",
            json={"message": {"parts": [TEXT], "model": "anthropic:claude-nope"}},
        )

        assert response.status_code == 400
        assert response.json()["code"] == "BAD_REQUEST"

    async def test_non_member_gets_404(
        self, client: AsyncClient, team: TeamModel, outsider: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(outsider)

        assert (await client.post(f"/api/teams/{team.id}/conversations", json={})).status_code == 404


class TestListConversations:
    async def test_pages_newest_first_and_hides_others_private_conversations(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        owner: UserModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        base = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
        titles = ["oldest", "middle", "newest"]
        for index, title in enumerate(titles):
            await seed_conversation(
                db_session, team=team, creator=owner, title=title, last_message_at=base + timedelta(minutes=index)
            )
        await seed_conversation(
            db_session,
            team=team,
            creator=owner,
            title="mine, private",
            visibility=ConversationVisibility.PRIVATE,
            last_message_at=base + timedelta(minutes=5),
        )
        await seed_conversation(
            db_session,
            team=team,
            creator=member,
            title="theirs, private",
            visibility=ConversationVisibility.PRIVATE,
            last_message_at=base + timedelta(minutes=6),
        )
        authenticate_as(owner)

        first = await client.get(f"/api/teams/{team.id}/conversations", params={"limit": 2})

        assert first.status_code == 200, first.text
        page = first.json()
        assert [row["title"] for row in page["items"]] == ["mine, private", "newest"]
        assert page["nextCursor"]

        second = await client.get(
            f"/api/teams/{team.id}/conversations", params={"limit": 2, "cursor": page["nextCursor"]}
        )

        assert second.status_code == 200, second.text
        assert [row["title"] for row in second.json()["items"]] == ["middle", "oldest"]
        assert "nextCursor" not in second.json()  # omitted on the last page

    async def test_invalid_cursor_is_400(
        self, client: AsyncClient, team: TeamModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.get(f"/api/teams/{team.id}/conversations", params={"cursor": "not-a-cursor"})

        assert response.status_code == 400

    async def test_non_member_gets_404(
        self, client: AsyncClient, team: TeamModel, outsider: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(outsider)

        assert (await client.get(f"/api/teams/{team.id}/conversations")).status_code == 404


class TestGetConversation:
    async def test_returns_messages_without_the_active_runs_assistant_message(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.RUNNING)
        await seed_message(
            db_session,
            conversation=conversation,
            role=MessageRole.ASSISTANT,
            position=1,
            run=run,
            parts=[{"type": "text", "text": "partial", "state": "streaming"}],
        )
        authenticate_as(member)

        response = await client.get(f"/api/conversations/{conversation.id}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["conversation"]["id"] == str(conversation.id)
        assert body["conversation"]["activeRun"]["id"] == str(run.id)
        assert [(m["role"], m["position"]) for m in body["messages"]] == [("user", 0)]

    async def test_finished_assistant_message_is_returned_with_typed_parts(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.SUCCEEDED)
        parts: list[JsonObject] = [
            {"type": "step-start"},
            {"type": "reasoning", "text": "think", "state": "done"},
            {"type": "text", "text": "Answer [1]", "state": "done"},
            {"type": "source-url", "sourceId": "1", "url": "https://docs.python.org/3.14/", "title": "Docs"},
            {
                "type": "tool-web_search",
                "toolCallId": "c1",
                "state": "output-available",
                "input": {"query": "python 3.14"},
                "output": {"results": []},
            },
            {"type": "data-research-task", "id": "a", "data": {"status": "done"}},
        ]
        await seed_message(
            db_session, conversation=conversation, role=MessageRole.ASSISTANT, position=1, run=run, parts=parts
        )
        authenticate_as(owner)

        response = await client.get(f"/api/conversations/{conversation.id}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert "activeRun" not in body["conversation"]
        assistant = body["messages"][1]
        assert assistant["runId"] == str(run.id)
        assert assistant["parts"] == parts

    async def test_private_conversation_is_404_for_other_members(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        owner: UserModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        private = await seed_conversation(
            db_session, team=team, creator=owner, visibility=ConversationVisibility.PRIVATE
        )
        authenticate_as(member)
        assert (await client.get(f"/api/conversations/{private.id}")).status_code == 404

        authenticate_as(owner)
        assert (await client.get(f"/api/conversations/{private.id}")).status_code == 200

    async def test_non_member_gets_404(
        self, client: AsyncClient, conversation: ConversationModel, outsider: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(outsider)

        assert (await client.get(f"/api/conversations/{conversation.id}")).status_code == 404
        assert (await client.get(f"/api/conversations/{uuid4()}")).status_code == 404


class TestUpdateConversation:
    async def test_creator_changes_title_and_visibility(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(owner)

        response = await client.patch(
            f"/api/conversations/{conversation.id}", json={"title": "Renamed", "visibility": "private"}
        )

        assert response.status_code == 200, response.text
        assert (response.json()["title"], response.json()["visibility"]) == ("Renamed", "private")
        await db_session.refresh(conversation)
        assert (conversation.title, conversation.visibility) == ("Renamed", "private")

    async def test_member_may_retitle_but_not_change_visibility(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(member)

        retitled = await client.patch(f"/api/conversations/{conversation.id}", json={"title": "By a member"})
        assert retitled.status_code == 200, retitled.text

        hidden = await client.patch(f"/api/conversations/{conversation.id}", json={"visibility": "private"})
        assert hidden.status_code == 403
        await db_session.refresh(conversation)
        assert (conversation.title, conversation.visibility) == ("By a member", "team")


class TestDeleteConversation:
    async def test_deletes_with_its_messages(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(owner)

        response = await client.delete(f"/api/conversations/{conversation.id}")

        assert response.status_code == 204
        assert await db_session.get(ConversationModel, conversation.id) is None
        assert await _messages(db_session, conversation.id) == []

    async def test_refused_while_a_run_is_active(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        await seed_run(db_session, conversation=conversation, requested_by=owner)
        authenticate_as(owner)

        response = await client.delete(f"/api/conversations/{conversation.id}")

        assert response.status_code == 409
        assert await db_session.get(ConversationModel, conversation.id) is not None


class TestCreateMessage:
    async def test_appends_the_message_and_queues_a_run_once(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(member)
        body = {
            "parts": [TEXT],
            "model": "anthropic:claude-haiku-5-5",
            "mode": "deep_research",
            "tools": {"webSearch": False},
        }

        response = await client.post(f"/api/conversations/{conversation.id}/messages", json=body)

        assert response.status_code == 201, response.text
        run = response.json()
        assert run["conversationId"] == str(conversation.id)
        assert (run["status"], run["mode"], run["model"]) == ("queued", "deep_research", "anthropic:claude-haiku-5-5")
        assert run["options"] == {"webSearch": False, "code": False}
        messages = await _messages(db_session, conversation.id)
        assert [(m.role, m.position, m.created_by) for m in messages] == [("user", 0, owner.id), ("user", 1, member.id)]
        assert messages[1].parts == [TEXT]
        await db_session.refresh(conversation)
        assert conversation.model == "anthropic:claude-haiku-5-5"

        second = await client.post(f"/api/conversations/{conversation.id}/messages", json={"parts": [TEXT]})

        assert second.status_code == 409
        assert len(await _messages(db_session, conversation.id)) == 2

    async def test_rejects_too_many_parts(
        self, client: AsyncClient, conversation: ConversationModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.post(f"/api/conversations/{conversation.id}/messages", json={"parts": [TEXT] * 14})

        assert response.status_code == 422


class TestRuns:
    async def test_active_run_is_404_until_one_is_queued(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(owner)
        url = f"/api/conversations/{conversation.id}/runs/active"
        assert (await client.get(url)).status_code == 404

        run = await seed_run(db_session, conversation=conversation, requested_by=owner)

        response = await client.get(url)
        assert response.status_code == 200
        assert response.json()["id"] == str(run.id)

    async def test_get_run_is_scoped_to_its_conversation(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.SUCCEEDED)
        other = await seed_conversation(db_session, team=team, creator=owner)
        authenticate_as(owner)

        response = await client.get(f"/api/conversations/{conversation.id}/runs/{run.id}")
        assert response.status_code == 200
        assert response.json()["status"] == "succeeded"

        assert (await client.get(f"/api/conversations/{other.id}/runs/{run.id}")).status_code == 404


class TestCancelRun:
    async def test_queued_run_is_cancelled_with_an_abort_event(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(db_session, conversation=conversation, requested_by=owner)
        authenticate_as(owner)

        response = await client.post(f"/api/conversations/{conversation.id}/runs/{run.id}/cancel")

        assert response.status_code == 204
        await db_session.refresh(run)
        assert (run.status, run.last_seq) == ("cancelled", 1)
        assert run.finished_at is not None
        events = await _events(db_session, run.id)
        assert [(e.seq, e.type, e.payload) for e in events] == [(1, "abort", {"type": "abort", "reason": "cancelled"})]

    async def test_running_run_gets_a_cancel_request(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(
            db_session, conversation=conversation, requested_by=owner, status=RunStatus.RUNNING, worker_id="w1"
        )
        authenticate_as(owner)

        response = await client.post(f"/api/conversations/{conversation.id}/runs/{run.id}/cancel")

        assert response.status_code == 204
        await db_session.refresh(run)
        assert run.status == "running"
        assert run.cancel_requested_at is not None
        assert await _events(db_session, run.id) == []

    async def test_finished_run_is_left_alone(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.SUCCEEDED)
        authenticate_as(owner)

        response = await client.post(f"/api/conversations/{conversation.id}/runs/{run.id}/cancel")

        assert response.status_code == 204
        await db_session.refresh(run)
        assert (run.status, run.cancel_requested_at, run.last_seq) == ("succeeded", None, 0)


class TestStreamRunEvents:
    async def test_replays_a_finished_run_and_closes(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.SUCCEEDED)
        await seed_run_events(db_session, run, CANONICAL)
        authenticate_as(owner)

        async with client.stream("GET", f"/api/conversations/{conversation.id}/runs/{run.id}/events") as response:
            stream = await _read_stream(response)

        assert stream.ids == list(range(1, len(CANONICAL) + 1))
        assert stream.chunks == [dict(chunk) for chunk in CANONICAL]
        assert stream.done
        assert stream.pings == 0

    async def test_after_and_last_event_id_resume_the_replay(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.SUCCEEDED)
        await seed_run_events(db_session, run, CANONICAL)
        authenticate_as(owner)
        url = f"/api/conversations/{conversation.id}/runs/{run.id}/events"

        async with client.stream("GET", url, params={"after": 3}) as response:
            by_query = await _read_stream(response)
        assert by_query.ids[0] == 4

        async with client.stream("GET", url, params={"after": 3}, headers={"Last-Event-ID": "5"}) as response:
            by_header = await _read_stream(response)
        assert by_header.ids[0] == 6
        assert by_header.done

    async def test_follows_a_running_run_until_its_terminal_event(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        fake_listener: FakeListener,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(
            db_session, conversation=conversation, requested_by=owner, status=RunStatus.RUNNING, worker_id="w1"
        )
        await seed_run_events(db_session, run, CANONICAL[:4])
        authenticate_as(owner)

        async def worker_writes_the_rest() -> None:
            # Only once the reader is parked on the listener: the test transaction's session is
            # shared with the reader, so the write must not overlap its reads.
            await asyncio.wait_for(fake_listener.waiting.wait(), 5)
            await seed_run_events(db_session, run, CANONICAL[4:])
            fake_listener.notify("run_events", f"{run.id}:{run.last_seq}")

        writer = asyncio.create_task(worker_writes_the_rest())
        async with client.stream("GET", f"/api/conversations/{conversation.id}/runs/{run.id}/events") as response:
            stream = await _read_stream(response)
        await writer

        assert stream.ids == list(range(1, len(CANONICAL) + 1))
        assert stream.chunks == [dict(chunk) for chunk in CANONICAL]
        assert stream.done
        assert fake_listener.notified == [("run_events", f"{run.id}:{len(CANONICAL)}")]

    async def test_terminal_run_without_a_terminal_event_gets_a_synthetic_error(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        conversation: ConversationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        run = await seed_run(db_session, conversation=conversation, requested_by=owner, status=RunStatus.FAILED)
        await seed_run_events(db_session, run, CANONICAL[:3])
        authenticate_as(owner)

        async with client.stream("GET", f"/api/conversations/{conversation.id}/runs/{run.id}/events") as response:
            stream = await _read_stream(response)

        assert stream.ids == [1, 2, 3, 4]
        last = stream.chunks[-1]
        assert isinstance(last, dict)
        assert last["type"] == "error"
        assert stream.done

    async def test_pings_while_idle_then_delivers_new_events(
        self,
        db_session: AsyncSession,
        sessions: SessionScope,
        fake_listener: FakeListener,
        conversation: ConversationModel,
        owner: UserModel,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The reader itself (no HTTP, so the body need not finish first): a keep-alive comment
        on every idle interval, then the rows written since, then the close."""
        monkeypatch.setattr(chat_settings, "chat_sse_ping_interval_s", 0)
        run = await seed_run(
            db_session, conversation=conversation, requested_by=owner, status=RunStatus.RUNNING, worker_id="w1"
        )
        reader = StreamRunEvents(sessions, fake_listener).execute(run_id=run.id, after=0)

        assert await anext(reader) == SSE_PING
        await seed_run_events(db_session, run, [{"type": "start", "messageId": "m1"}, {"type": "finish"}])

        frames = [frame async for frame in reader]

        assert frames[0].startswith(b"id: 1\n")
        assert frames[1].startswith(b'id: 2\ndata: {"type":"finish"}')
        assert frames[-1] == b"data: [DONE]\n\n"

    async def test_unknown_run_is_404(
        self, client: AsyncClient, conversation: ConversationModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.get(f"/api/conversations/{conversation.id}/runs/{uuid4()}/events")

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")


class TestListModels:
    async def test_lists_the_configured_models_with_one_default(
        self, client: AsyncClient, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.get("/api/chat/models")

        assert response.status_code == 200, response.text
        models = response.json()
        assert [m["id"] for m in models] == [
            "anthropic:claude-opus-5-5",
            "anthropic:claude-sonnet-5-5",
            "anthropic:claude-haiku-5-5",
        ]
        assert [m["id"] for m in models if m["isDefault"]] == ["anthropic:claude-opus-5-5"]
        assert models[0] == {
            "id": "anthropic:claude-opus-5-5",
            "provider": "anthropic",
            "modelId": "claude-opus-5-5",
            "displayName": "Claude Opus 5.5",
            "tier": "frontier",
            "supportsTools": True,
            "supportsReasoning": True,
            "supportsVision": True,
            "isDefault": True,
        }

    async def test_requires_auth(self, client: AsyncClient) -> None:
        assert (await client.get("/api/chat/models")).status_code == 401
