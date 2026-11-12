"""Protocolo daemon → pílula: uma mensagem por linha de texto."""
from utter.protocol import Recording, Waiting, Done, Failed, Hide, encode, decode


def test_recording_roundtrips_level_and_elapsed():
    msg = decode(encode(Recording(level=0.42, elapsed=4.25)))
    assert msg == Recording(level=0.42, elapsed=4.25)


def test_encoded_message_is_single_line():
    assert encode(Failed("linha 1\nlinha 2")).count("\n") == 1


def test_failed_keeps_message_with_spaces_and_accents():
    assert decode(encode(Failed("serviço parado — tente de novo"))) == Failed(
        "serviço parado — tente de novo")


def test_simple_states_roundtrip():
    for msg in (Waiting(), Done(), Hide()):
        assert decode(encode(msg)) == msg


def test_garbage_line_decodes_to_none():
    assert decode("bogus 1 2 3\n") is None
    assert decode("rec not-a-number 1\n") is None
