from datetime import timedelta

from schedule_visualizer.config import DEFAULT_TTL_SECONDS, DEFAULT_WINDOW_DAYS, Config


def test_defaults_when_env_empty() -> None:
    config = Config.from_env({})
    assert config.ttl == timedelta(seconds=DEFAULT_TTL_SECONDS)
    assert config.window_days == DEFAULT_WINDOW_DAYS
    assert config.team_source == "tag"
    assert config.team_tag_prefix == "team:"


def test_reads_overrides() -> None:
    config = Config.from_env(
        {
            "SCHEDULE_VIZ_TTL_SECONDS": "120",
            "SCHEDULE_VIZ_WINDOW_DAYS": "7",
            "SCHEDULE_VIZ_TEAM_SOURCE": "bundle",
            "SCHEDULE_VIZ_TEAM_TAG_PREFIX": "squad-",
        }
    )
    assert config.ttl == timedelta(seconds=120)
    assert config.window_days == 7
    assert config.team_source == "bundle"
    assert config.team_tag_prefix == "squad-"


def test_unknown_team_source_falls_back_to_tag() -> None:
    assert Config.from_env({"SCHEDULE_VIZ_TEAM_SOURCE": "nonsense"}).team_source == "tag"


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
