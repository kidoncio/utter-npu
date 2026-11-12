"""UI language follows the desktop locale: Portuguese for pt*, English otherwise."""
from utter.i18n import strings_for


def test_brazilian_portuguese_locale_gets_portuguese():
    assert strings_for({"LANG": "pt_BR.UTF-8"})["speak"] == "Fale agora"


def test_lc_all_overrides_lang():
    assert strings_for({"LANG": "pt_BR.UTF-8", "LC_ALL": "en_US.UTF-8"})["speak"] == "Speak now"


def test_unknown_or_missing_locale_falls_back_to_english():
    assert strings_for({"LANG": "de_DE.UTF-8"})["speak"] == "Speak now"
    assert strings_for({})["speak"] == "Speak now"


def test_every_language_has_the_same_keys():
    en, pt = strings_for({"LANG": "C"}), strings_for({"LANG": "pt_PT"})
    assert en.keys() == pt.keys()
