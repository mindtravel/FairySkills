"""Generic agent-trace adapter: one normalized TraceFile per row."""
from __future__ import annotations

from fairyview.record import Rendered
from fairyview.trace import TraceFile, trace_panels
from fairyview.views import View, register_row


class TraceView(View):
    name = "trace_rows"

    def columns(self) -> list[str]:
        return ["trajectories"]

    def render(self, row: dict) -> Rendered | None:
        trace = TraceFile.from_dict(row)
        panels = trace_panels(trace)
        if not panels:
            return None
        fields = list(trace.fields)
        fields.extend([
            ["trajectories", len(trace.trajectories)],
            ["steps", sum(len(t.steps) for t in trace.trajectories)],
        ])
        return Rendered(panels=panels, fields=fields)


@register_row("trace_rows")
def trace_rows(cfg: dict, source) -> TraceView:
    return TraceView(name="trace_rows", cfg=cfg, source=source)
