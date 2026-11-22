import pytest

from smartkeeper.rules import RulesService
from tests.fixtures import FakeDice


@pytest.fixture
def rules() -> RulesService:
    return RulesService(FakeDice())
