"""[0 이영] 배포 진입점에서 집중 화면이 실제로 열리는지 확인한다."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_deployment_entrypoint_loads():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "근거관문"
    app.button(key="fin_manual_load").click().run()
    app.button(key="fin_compute").click().run()
    assert not app.exception
    assert app.session_state["fin_report"]["can_approve"] is True
    assert app.session_state["fin_report"]["human_approval"]["status"] == "PENDING"
