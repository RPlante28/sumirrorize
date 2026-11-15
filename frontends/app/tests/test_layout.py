import pytest

from app.layout import LayoutError, validate_layout


def widget(**changes):
    return {"key": "weather", "enabled": True, "x": .1, "y": .1, "w": .3, "h": .2,
            "variant": "current", **changes}


def test_layout_accepts_known_variant():
    assert validate_layout({"widgets": [widget()]})[0]["variant"] == "current"


@pytest.mark.parametrize("change", [
    {"x": -1}, {"w": 0}, {"x": .8, "w": .3}, {"variant": "made-up"}, {"enabled": "yes"},
])
def test_layout_rejects_invalid_widget(change):
    with pytest.raises(LayoutError):
        validate_layout({"widgets": [widget(**change)]})
