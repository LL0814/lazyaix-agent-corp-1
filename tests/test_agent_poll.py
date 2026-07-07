from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent import Agent
from workflow.state import Workflow, WorkflowStatus


def _make_agent() -> Agent:
    return Agent(context=MagicMock(), memory=MagicMock())


@pytest.mark.asyncio
async def test_poll_workflow_result_returns_on_terminal_status():
    agent = _make_agent()
    store = AsyncMock()
    wf = Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="hi",
        status=WorkflowStatus.COMPLETED,
    )
    store.get_workflow = AsyncMock(return_value=wf)

    result = await agent._poll_workflow_result(
        store,
        "wf-1",
        timeout_seconds=1.0,
        interval_seconds=0.1,
    )

    assert result is wf
    assert result.status == WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_poll_workflow_result_returns_none_on_timeout():
    agent = _make_agent()
    store = AsyncMock()
    wf = Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="hi",
        status=WorkflowStatus.EXECUTING,
    )
    store.get_workflow = AsyncMock(return_value=wf)

    result = await agent._poll_workflow_result(
        store,
        "wf-1",
        timeout_seconds=0.2,
        interval_seconds=0.05,
    )

    assert result is None


@pytest.mark.asyncio
async def test_poll_workflow_result_eventually_completes():
    agent = _make_agent()
    store = AsyncMock()
    pending = Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="hi",
        status=WorkflowStatus.EXECUTING,
    )
    completed = Workflow(
        workflow_id="wf-1",
        trace_id="tr-1",
        user_input="hi",
        status=WorkflowStatus.COMPLETED,
    )
    store.get_workflow = AsyncMock(side_effect=[pending, pending, completed])

    result = await agent._poll_workflow_result(
        store,
        "wf-1",
        timeout_seconds=1.0,
        interval_seconds=0.05,
    )

    assert result is completed
