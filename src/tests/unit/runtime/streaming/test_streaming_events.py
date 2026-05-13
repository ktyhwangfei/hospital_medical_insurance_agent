import json

from src.runtime.api.streaming import sse_event


def test_sse_event_formats_json_payload():
    raw = sse_event('step', {'step': 'intent_detection', 'message': '正在识别意图'})

    assert raw.startswith('event: step\n')
    assert raw.endswith('\n\n')
    data_line = raw.split('\n')[1]
    assert data_line.startswith('data: ')
    assert json.loads(data_line.removeprefix('data: ')) == {
        'step': 'intent_detection',
        'message': '正在识别意图',
    }
