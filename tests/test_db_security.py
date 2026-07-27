from app.core.db import engine


def test_sqlalchemy_engine_hides_bound_parameters():
    assert engine.hide_parameters is True
