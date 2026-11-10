"""Queue invariants tested independently of a browser or database."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('scenario',['strict-persistence','failed-initial-read','edited-before-restore','late-owner','restore-before-submit','delete-serialized','closed-during-hash','logout-queued','durable-replay'])
def test_draft_lifecycle_protocol(scenario):
    result=subprocess.run(['node',str(ROOT/'tests/audit_frontend_callbacks.js'),scenario,str(ROOT/'static/improvements.js')],capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'scenario':scenario,'passed':True}

def test_calendar_orders_lesson_and_localized_consultation_by_canonical_time():
    result=subprocess.run(['node',str(ROOT/'tests/audit_render_callbacks.js'),str(ROOT/'static/campus.js')],capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'scenario':'calendar-canonical-order','passed':True}
