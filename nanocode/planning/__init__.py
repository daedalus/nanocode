"""Planning engine for task decomposition and execution."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from nanocode.state import ExecutionPlan, TaskStep


class PlanStrategy(Enum):
    """Planning strategies."""

    LINEAR = "linear"
    PARALLEL = "parallel"
    ADAPTIVE = "adaptive"


@dataclass
class PlanningContext:
    """Context for planning."""

    task: str
    tools: list[dict]
    history: list[dict]
    max_steps: int = 20
    max_retries: int = 3
    checkpoint_enabled: bool = True


class TaskPlanner:
    """Plans task execution with step decomposition."""

    def __init__(self, llm, registry):
        self.llm = llm
        self.registry = registry
        self._current_plan: ExecutionPlan | None = None

    async def create_plan(self, context: PlanningContext) -> ExecutionPlan:
        """Create an execution plan for a task."""
        goal = context.task

        prompt = f"""You are a task planning system. Break down the following task into specific, executable steps.

Available tools:
{json.dumps(context.tools, indent=2)}

Task: {goal}

Create a detailed plan with numbered steps. Each step should:
1. Have a clear description
2. Specify which tool to use (if any)
3. Include necessary arguments

Respond with a JSON plan in this format:
{{
    "steps": [
        {{
            "id": "step_1",
            "description": "Description of what to do",
            "tool": "tool_name" (or null if no tool needed),
            "args": {{"arg1": "value1"}}
        }}
    ]
}}"""

        from nanocode.llm import Message

        response = await self.llm.chat([Message("user", prompt)])

        try:
            plan_data = json.loads(response.content)
        except Exception:
            plan_data = self._parse_fallback_plan(response.content)

        steps = []
        for i, step_data in enumerate(plan_data.get("steps", [])):
            step = TaskStep(
                id=step_data.get("id", f"step_{i + 1}"),
                description=step_data.get("description", ""),
                tool=step_data.get("tool"),
                args=step_data.get("args", {}),
            )
            steps.append(step)

        plan = ExecutionPlan(id=str(uuid.uuid4())[:8], goal=goal, steps=steps)
        self._current_plan = plan
        return plan

    def _parse_fallback_plan(self, content: str) -> dict:
        """Parse plan from plain text response."""
        steps = []
        for line in content.split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-")):
                desc = line.lstrip("0123456789.- ").strip()
                if desc:
                    steps.append({"id": f"step_{len(steps) + 1}", "description": desc})
        return {"steps": steps}

    def get_current_plan(self) -> ExecutionPlan | None:
        """Get the current plan."""
        return self._current_plan

    def update_step(self, step_id: str, result: Any = None, error: str = None):
        """Update step execution result."""
        if not self._current_plan:
            return

        for step in self._current_plan.steps:
            if step.id == step_id:
                step.result = result
                step.error = error
                step.completed_at = datetime.now()
                if error:
                    step.status = "failed"
                else:
                    step.status = "complete"
                break

    def mark_step_running(self, step_id: str):
        """Mark a step as running."""
        if not self._current_plan:
            return

        for step in self._current_plan.steps:
            if step.id == step_id:
                step.status = "running"
                step.started_at = datetime.now()
                break


class PlanExecutor:
    """Executes plans with progress tracking and checkpointing."""

    def __init__(
        self, planner: TaskPlanner, executor, checkpoint_dir: str = ".nanocode"
    ):
        self.planner = planner
        self.executor = executor
        self.checkpoint_dir = checkpoint_dir
        self._current_step = 0
        self._retry_count = 0

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        max_retries: int = 3,
        checkpoint_enabled: bool = True,
    ) -> dict:
        """Execute a plan step by step."""
        results = []

        for i, step in enumerate(plan.steps):
            self._current_step = i
            plan.current_step = i
            self.planner.mark_step_running(step.id)

            if checkpoint_enabled:
                self._save_checkpoint(plan)

            try:
                if step.tool:
                    result = await self.executor.execute(step.tool, step.args)
                else:
                    result = await self._execute_llm_step(step.description)

                self.planner.update_step(
                    step.id, result=result.content, error=result.error
                )
                results.append({"step": step.id, "result": result})

                if not result.success:
                    if self._retry_count < max_retries:
                        self._retry_count += 1
                        continue
                    else:
                        return {
                            "success": False,
                            "error": f"Step {step.id} failed: {result.error}",
                            "results": results,
                        }
            except Exception as e:
                self.planner.update_step(step.id, error=str(e))
                if self._retry_count < max_retries:
                    self._retry_count += 1
                    continue
                return {"success": False, "error": str(e), "results": results}

        return {"success": True, "results": results}

    async def _execute_llm_step(self, description: str) -> Any:
        """Execute a step that requires LLM reasoning."""
        from nanocode.llm import Message
        from nanocode.tools import ToolResult

        prompt = f"Execute this step: {description}"
        response = await self.planner.llm.chat([Message("user", prompt)])

        return ToolResult(success=True, content=response.content)

    def _save_checkpoint(self, plan: ExecutionPlan):
        """Save execution checkpoint."""
        import os

        os.makedirs(self.checkpoint_dir, exist_ok=True)
        path = os.path.join(self.checkpoint_dir, f"checkpoint_{plan.id}.json")
        plan.save_checkpoint(plan.checkpoint_file or path)

    def load_checkpoint(self, plan_id: str) -> ExecutionPlan | None:
        """Load a checkpoint."""
        import os

        path = os.path.join(self.checkpoint_dir, f"checkpoint_{plan_id}.json")
        if os.path.exists(path):
            from pathlib import Path

            return ExecutionPlan.load_checkpoint(Path(path))
        return None


class PlanMonitor:
    """Monitors plan execution and handles replanning."""

    def __init__(self, llm):
        self.llm = llm

    async def evaluate_progress(
        self, plan: ExecutionPlan, recent_results: list[dict]
    ) -> dict:
        """Evaluate execution progress and determine if replanning is needed."""
        from nanocode.llm import Message

        prompt = f"""Evaluate the progress of this plan execution:

Goal: {plan.goal}

Completed steps:
{json.dumps([{"id": s.id, "description": s.description, "status": s.status} for s in plan.steps if s.status == "complete"], indent=2)}

Recent results:
{json.dumps(recent_results, indent=2)}

Determine if:
1. The plan is on track to complete the goal
2. The plan needs modification
3. The goal has been achieved

Respond with:
{{
    "status": "on_track" | "needs_modification" | "complete" | "failed",
    "reason": "explanation",
    "suggested_changes": ["change 1", "change 2"] (if any)
}}"""

        response = await self.llm.chat([Message("user", prompt)])

        try:
            return json.loads(response.content)
        except Exception:
            return {"status": "unknown", "reason": response.content}

    async def create_replan(
        self, original_plan: ExecutionPlan, failed_step_id: str, error: str
    ) -> ExecutionPlan:
        """Create a revised plan after a failure."""
        from nanocode.llm import Message

        prompt = f"""A plan failed. Create a revised plan.

Original Goal: {original_plan.goal}

Original Plan:
{json.dumps([{"id": s.id, "description": s.description, "tool": s.tool, "status": s.status} for s in original_plan.steps], indent=2)}

Failed step: {failed_step_id}
Error: {error}

Create a revised plan that:
1. Either fixes the failed step or works around it
2. Keeps completed steps
3. Adjusts remaining steps as needed

Respond in the same JSON format as before."""

        response = await self.llm.chat([Message("user", prompt)])

        try:
            json.loads(response.content)
        except Exception:
            pass

        steps = []
        completed = False
        for s in original_plan.steps:
            if s.status == "complete":
                steps.append(s)
            elif s.id == failed_step_id:
                completed = True
            elif completed:
                new_step = TaskStep(
                    id=s.id,
                    description=s.description,
                    tool=s.tool,
                    args=s.args,
                )
                steps.append(new_step)

        return ExecutionPlan(
            id=str(uuid.uuid4())[:8],
            goal=original_plan.goal,
            steps=steps,
        )
