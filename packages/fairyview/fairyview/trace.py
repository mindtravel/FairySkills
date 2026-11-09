"""Common agent-trace model and renderer.

Format-specific adapters only normalize into TraceFile. The page structure
(file -> trajectory -> step) and the thinking/tool presentation stay here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from fairyview.schema import Panel, ReviewRecord


@dataclass
class TraceStep:
    step_id: str
    role: str
    visible: str = ""
    thinking: str = ""
    tool_calls: list[Any] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    label: str = ""
    collapsed: bool = False


@dataclass
class TraceTrajectory:
    trajectory_id: str
    label: str
    model: str = ""
    effort: str = ""
    steps: list[TraceStep] = field(default_factory=list)
    collapsed: bool = False


@dataclass
class TraceFile:
    file_id: str
    source: str = ""
    format: str = ""
    trajectories: list[TraceTrajectory] = field(default_factory=list)
    fields: list[list[Any]] = field(default_factory=list)
    facets: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: dict) -> "TraceFile":
        trajectories = []
        for trajectory in row.get("trajectories", []):
            steps = [TraceStep(**step) for step in trajectory.get("steps", [])]
            trajectories.append(
                TraceTrajectory(
                    trajectory_id=str(trajectory.get("trajectory_id") or trajectory.get("id") or "trajectory"),
                    label=trajectory.get("label") or trajectory.get("trajectory_id") or "trajectory",
                    model=trajectory.get("model", ""),
                    effort=trajectory.get("effort", ""),
                    steps=steps,
                    collapsed=bool(trajectory.get("collapsed", False)),
                )
            )
        return cls(
            file_id=str(row.get("file_id") or row.get("id") or "trace"),
            source=row.get("source", ""),
            format=row.get("format", ""),
            trajectories=trajectories,
            fields=row.get("fields", []),
            facets=row.get("facets", {}),
            provenance=row.get("provenance", {}),
        )


def _json(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def trace_panels(trace: TraceFile) -> list[Panel]:
    panels: list[Panel] = []
    for trajectory_index, trajectory in enumerate(trace.trajectories):
        traj_id = trajectory.trajectory_id or f"trajectory-{trajectory_index + 1}"
        traj_label = trajectory.label or f"trajectory {trajectory_index + 1}"
        for step_index, step in enumerate(trajectory.steps):
            sid = step.step_id or f"{traj_id}:step:{step_index + 1}"
            step_label = step.label or f"step {step_index + 1} · {step.role}"
            common = {"group_path": [traj_id, sid], "group_labels": [traj_label, step_label],
                      "group_collapsed": trajectory.collapsed}
            if step.visible.strip():
                panels.append(Panel(role=step.role, label="visible", text=step.visible,
                                    collapsed=step.collapsed, **common))
            if step.thinking.strip():
                panels.append(Panel(role="thinking", label="thinking", text=step.thinking,
                                    collapsed=True, **common))
            if step.tool_calls:
                panels.append(Panel(role="tool_call", label="tool calls", text=_json(step.tool_calls),
                                    collapsed=True, **common))
            if step.tool_results:
                panels.append(Panel(role="tool_result", label="tool results", text=_json(step.tool_results),
                                    collapsed=True, **common))
    return panels


def make_trace_record(trace: TraceFile) -> ReviewRecord:
    fields = list(trace.fields)
    fields.extend([
        ["trajectories", len(trace.trajectories)],
        ["steps", sum(len(t.steps) for t in trace.trajectories)],
    ])
    return ReviewRecord(
        id=trace.file_id,
        facets=trace.facets,
        fields=fields,
        panels=trace_panels(trace),
        provenance=trace.provenance,
    )
