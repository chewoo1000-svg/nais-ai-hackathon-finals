"""배포 설정 회귀 시험: 루트에서 실행할 때 실제로 적용되는 Streamlit 설정이 있는지 확인한다.

# [작성: 0 이영 · Claude] 2026-09-30 23:59 KST — finals/.streamlit/config.toml만 있으면 루트 실행(README·Cloud)에서 적용되지 않는다.
"""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_root_streamlit_config_applies_upload_cap_and_theme():
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))
    assert config["server"]["maxUploadSize"] <= 1
    assert config["browser"]["gatherUsageStats"] is False
    assert config["theme"]["base"] == "light"


def test_upload_cap_is_not_below_the_report_size_the_pipeline_accepts():
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))
    assert config["server"]["maxUploadSize"] * 1024 * 1024 >= 262144   # finals_pipeline._strict_json의 상한
