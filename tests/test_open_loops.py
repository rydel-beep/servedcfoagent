"""Pillar 1: reminders/drop + the INTERNAL-ONLY boundary (no client-deal loops, no outbound)."""
import open_loops as OL


def test_remind_and_drop():
    r, h = OL.handle_command("remind me to review the quarterly on Friday")
    assert h and "remind you" in r.lower() and "friday" in r.lower()
    d, hd = OL.handle_command("drop it")
    assert hd and "won't bring that up" in d.lower()


def test_reminder_matcher_scope():
    # a plain statement is NOT a reminder
    assert OL.handle_command("cash looks fine today")[1] is False


def test_boundary_refuses_outbound_client_contact():
    r, h = OL.handle_command("remind me to email the client about the invoice")
    assert h and ("don't contact clients" in r.lower() or "off limits" in r.lower())
    r2, h2 = OL.handle_command("chase the lead for me")
    # 'chase the lead' isn't a remind-me; must not create a loop
    assert h2 is False or "don't contact" in (r2 or "").lower()


def test_outbound_regex_flags_client_contact():
    assert OL._OUTBOUND_CLIENT.search("email the client about it")
    assert OL._OUTBOUND_CLIENT.search("follow up with the lead")
    assert not OL._OUTBOUND_CLIENT.search("review the quarterly report")
