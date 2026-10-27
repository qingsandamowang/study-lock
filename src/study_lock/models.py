from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Task:
    task_id: str
    label: str
    completed: bool = False


@dataclass
class LearningResource:
    title: str
    kind: str
    location: str
    purpose: str = ""
    output: str = ""
    chapters: str = ""


@dataclass
class ProjectMilestone:
    label: str
    completed: bool = False
    detail: str = ""


@dataclass
class DailyPlan:
    plan_date: date
    title: str
    tasks: list[Task]
    allowed_apps: set[str]
    allowed_domains: set[str]
    learning_record: str
    goal: str = ""
    reflection_questions: list[str] = field(default_factory=list)
    workflow: list[Task] = field(default_factory=list)
    resources: list[LearningResource] = field(default_factory=list)
    project_milestones: list[ProjectMilestone] = field(default_factory=list)

    def is_complete(self) -> bool:
        tasks = self.workflow or self.tasks
        return all(task.completed for task in tasks)
