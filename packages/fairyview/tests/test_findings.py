import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fairyview.schema import Finding, ReviewRecord


def test_span_free_finding_survives_serialization():
    record = ReviewRecord(id='s', findings=[Finding('issue1', 'Encrypted thinking', locations=['message1/block1'])])
    row = record.to_dict()
    assert row['findings'][0]['locations'] == ['message1/block1']
    assert row['panels'] == []


def test_duplicate_finding_ids_are_rejected():
    with pytest.raises(ValueError, match='unique'):
        ReviewRecord(id='s', findings=[Finding('same', 'a'), Finding('same', 'b')]).validate()


def test_renderer_converts_python_unicode_offsets_for_javascript(tmp_path):
    if not shutil.which('node'):
        pytest.skip('node unavailable')
    app = (Path(__file__).parents[1] / 'template/app.js').read_text()
    # Exercise the renderer's range calculation against the public Python span contract.
    start = app.index('  function visibleSpans(')
    end = app.index('\n  // Numbered marks:', start)
    source = app[start:end]
    source += '\nconst p = ' + json.dumps({'text': '😀前😀后', 'spans': [{'start': 2, 'end': 4, 'kind': 'warning'}]}) + ';\n'
    source += 'const s=visibleSpans(p)[0]; if(p.text.slice(s.start,s.end)!=="😀后") process.exit(1);\n'
    path = tmp_path / 'ranges.js'
    path.write_text(source)
    subprocess.run(['node', str(path)], check=True)


def test_grouped_panels_preserve_original_text_and_display_metadata():
    from fairyview.schema import Panel, ReviewRecord
    panel = Panel(role='thinking', label='thinking', text='原文😀', group='msg1',
                  group_label='message 1', collapsed=True, group_collapsed=True)
    data = ReviewRecord(id='s', panels=[panel]).to_dict()['panels'][0]
    assert data['text'] == '原文😀'
    assert data['group'] == 'msg1' and data['collapsed'] and data['group_collapsed']
