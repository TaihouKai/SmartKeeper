import pytest

from smartkeeper.rules import RulesService


@pytest.fixture
def rules() -> RulesService:
    return RulesService()
