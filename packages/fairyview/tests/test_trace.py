from pathlib import Path

from fairyview.build import build
from fairyview.schema import Panel
from fairyview.trace import TraceFile, TraceStep, TraceTrajectory, make_trace_record


def trace_file():
    return TraceFile(
        file_id='trace-1',
        source='fixture',
        format='normalized',
        facets={'source': 'fixture'},
        fields=[['model', 'test']],
        trajectories=[
            TraceTrajectory(
                trajectory_id='traj-1',
                label='trajectory 1',
                steps=[
                    TraceStep('s1', 'system', visible='context', collapsed=True),
                    TraceStep('s2', 'user', visible='fix it'),
                    TraceStep('s3', 'assistant', visible='working', thinking='plan',
                              tool_calls=[{'name': 'check'}], tool_results=[{'ok': True}]),
                ],
            )
        ],
    )


def test_trace_record_uses_nested_trajectory_and_step_groups():
    record = make_trace_record(trace_file())
    record.validate()
    assert all(panel.group_path == ['traj-1', panel.group_path[1]] for panel in record.panels)
    assert [panel.label for panel in record.panels] == [
        'visible', 'visible', 'visible', 'thinking', 'tool calls', 'tool results'
    ]
    assert [panel.role for panel in record.panels] == ['system', 'user', 'assistant', 'thinking', 'tool_call', 'tool_result']
    assert record.panels[3].collapsed is True


def test_trace_rows_builds_from_normalized_jsonl(tmp_path: Path):
    import json
    row = {
        'file_id': 'trace-1',
        'source': 'fixture',
        'trajectories': [{
            'trajectory_id': 't1',
            'label': 'trajectory 1',
            'steps': [
                {'step_id': 's1', 'role': 'user', 'visible': 'fix it'},
                {'step_id': 's2', 'role': 'assistant', 'visible': 'done', 'thinking': 'plan'},
            ],
        }],
        'fields': [['model', 'test']],
    }
    data = tmp_path / 'traces.jsonl'
    data.write_text(json.dumps(row) + '\n', encoding='utf-8')
    cfg = tmp_path / 'trace.toml'
    cfg.write_text(f'title="trace"\nid_field="file_id"\nfacets=["source"]\n[source]\nkind="trace_rows"\npath="{data}"\n', encoding='utf-8')
    out = build(str(cfg), str(tmp_path / 'out'))
    assert (out / 'records.js').exists()
    assert 'trace-1' in (out / 'records.js').read_text(encoding='utf-8')
