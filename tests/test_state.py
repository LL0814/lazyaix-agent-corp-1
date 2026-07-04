from workflow.state import Task, TaskStatus, Workflow, WorkflowStatus


def test_task_defaults():
    task = Task(
        task_id="write_001",
        task_type="write",
        target_capability="writer",
        instructions="write a poem",
    )
    assert task.status == TaskStatus.PENDING
    assert task.dependencies == []
    assert task.required_for_completion is True


def test_workflow_defaults():
    wf = Workflow(workflow_id="wf-1", trace_id="tr-1", user_input="hello")
    assert wf.status == WorkflowStatus.CREATED
    assert wf.tasks == {}
