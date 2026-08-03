"""The pronunciation normalizer — the 'creepy voice' fix. TTS input only; captions untouched."""
from speech_normalize import normalize_for_speech as N


def test_currency_exact():
    assert N("$3,050") == "three thousand and fifty dollars"
    assert N("we collected $172k this quarter") == \
        "we collected one hundred and seventy-two thousand dollars this quarter"
    assert "four dollars fifty-one cents charge" in N("a $4.51 charge")


def test_ratio_and_multiple():
    out = N("LTGP:CAC is 4.51x")
    assert out == "L T G P to C A C is four point five one times"


def test_acronyms_and_names():
    assert N("MRR is up; sync Xero tonight") == "M R R is up; sync Zero tonight"
    assert "row-ass" in N("ROAS held steady")


def test_percent_and_iso_date():
    assert N("22% on 2026-07-27") == "twenty-two percent on July twenty-seventh"


def test_eye_formatting_stripped():
    out = N("**HOOK**\n- point one\n- point two ✅\n`code` and | table |")
    assert "*" not in out and "-" not in out.split()[0] and "✅" not in out and "|" not in out and "`" not in out


def test_bad_turn_specimen_end_to_end():
    src = "The actual LTGP:CAC is 3.75x (last 30 days) — that's the real number, not a scenario."
    out = N(src)
    assert "L T G P to C A C" in out and "three point seven five times" in out
    assert "(" not in out and "—" not in out
    assert "last 30 days" in out          # the aside is kept, spoken as a clause


def test_thousands_separator_and_lexicon_env(monkeypatch):
    assert N("1,650 tasks cached") == "one thousand, six hundred and fifty tasks cached"
    monkeypatch.setenv("SPEECH_LEXICON", '{"Pizzicotto": "pizzi-COTT-oh"}')
    assert "pizzi-COTT-oh" in N("Pizzicotto looks fine")


def test_never_raises_returns_original(monkeypatch):
    import speech_normalize as SN
    monkeypatch.setattr(SN, "_strip_eye_format", lambda t: 1 / 0)
    assert SN.normalize_for_speech("keep me intact") == "keep me intact"
