import pytest

@pytest.mark.quick
def test_quick_marker_baseline():
    # Test ultra rapide servant d'exemple pour le profil 'quick'
    assert 1 + 1 == 2
