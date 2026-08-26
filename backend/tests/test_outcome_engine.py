"""
Outcome engine tests.

Two properties carry the whole measurement claim: draws are reproducible
independent of processing order, and a recovery that would have happened
anyway is not counted as attributable. Everything else is bookkeeping.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import json
from pathlib import Path

from app import outcome_engine
from app.outcome_engine import Behaviour, attempt_outcome, control_outcome, draw


DATASET = Path(__file__).parent.parent / "data" / "test_batch_50.json"


# --- Determinism ------------------------------------------------------------


def test_draw_is_reproducible():
    a = draw("pay_x", 42, "respond:whatsapp_link", 0)
    b = draw("pay_x", 42, "respond:whatsapp_link", 0)
    assert a == b
    assert 0.0 <= a < 1.0


def test_draw_varies_across_record_purpose_and_attempt():
    base = draw("pay_x", 42, "respond:whatsapp_link", 0)
    assert draw("pay_y", 42, "respond:whatsapp_link", 0) != base
    assert draw("pay_x", 43, "respond:whatsapp_link", 0) != base
    assert draw("pay_x", 42, "natural", 0) != base
    assert draw("pay_x", 42, "respond:whatsapp_link", 1) != base


def test_outcome_does_not_depend_on_processing_order():
    """
    Keying draws on the record rather than pulling from a shared stream is
    what makes a partial re-run, a reordering, or parallel processing produce
    the same answer. A sequential RNG would not survive any of those.
    """
    behaviour = Behaviour(natural_recovery_hours=None,
                          responds_to={"whatsapp_link": 0.5})
    ids = [f"pay_{i:03d}" for i in range(50)]

    forward = [attempt_outcome(i, behaviour, "whatsapp_link", 0, 7).recovered
               for i in ids]
    backward = [attempt_outcome(i, behaviour, "whatsapp_link", 0, 7).recovered
                for i in reversed(ids)]

    assert forward == list(reversed(backward))


# --- Attribution ------------------------------------------------------------


def test_payment_made_before_our_attempt_is_not_attributable():
    """
    The customer paid at +0.5h; our WhatsApp goes out at +1h. The money
    arrived, but we did not cause it. Counting this is exactly how recovery
    tools overstate their value.
    """
    behaviour = Behaviour(natural_recovery_hours=0.5,
                          responds_to={"whatsapp_link": 1.0})

    result = attempt_outcome("pay_early", behaviour, "whatsapp_link", 0, 1)

    assert result.recovered is True
    assert result.attributable is False
    assert "not attributable" in result.reason


def test_payment_after_our_attempt_is_attributable():
    behaviour = Behaviour(natural_recovery_hours=48.0,
                          responds_to={"whatsapp_link": 1.0})

    result = attempt_outcome("pay_late", behaviour, "whatsapp_link", 0, 1)

    assert result.recovered is True
    assert result.attributable is True


def test_no_response_is_not_recovered():
    behaviour = Behaviour(natural_recovery_hours=None,
                          responds_to={"whatsapp_link": 0.0})

    result = attempt_outcome("pay_none", behaviour, "whatsapp_link", 0, 1)

    assert result.recovered is False
    assert result.attributable is False


def test_unknown_channel_never_recovers():
    behaviour = Behaviour(natural_recovery_hours=None, responds_to={})
    assert attempt_outcome("p", behaviour, "carrier_pigeon", 0, 1).recovered is False


# --- Control arm ------------------------------------------------------------


def test_control_recovers_only_if_it_would_have_anyway():
    would = Behaviour(natural_recovery_hours=10.0, responds_to={})
    would_not = Behaviour(natural_recovery_hours=None, responds_to={})

    assert control_outcome(would).recovered is True
    assert control_outcome(would_not).recovered is False


def test_control_recovery_is_never_attributable():
    behaviour = Behaviour(natural_recovery_hours=10.0, responds_to={})
    assert control_outcome(behaviour).attributable is False


def test_natural_recovery_outside_the_window_does_not_count():
    late = Behaviour(
        natural_recovery_hours=outcome_engine.OBSERVATION_WINDOW_HOURS + 1,
        responds_to={},
    )
    assert control_outcome(late).recovered is False


# --- Holdout assignment -----------------------------------------------------


def _dataset():
    records = json.loads(DATASET.read_text(encoding="utf-8"))
    from app.classifier import RULE_MAP
    for record in records:
        mapped = RULE_MAP.get(record["error"]["reason"])
        # Unmapped reasons are a stratum of their own: their real class is
        # not knowable without a model call, and the arm must be fixed first.
        record["_failure_class"] = mapped.value if mapped else "UNDIAGNOSED"
    return records


def test_holdout_is_stable_for_a_given_seed():
    records = _dataset()
    first = outcome_engine.assign_holdout(records, 99, 20)
    second = outcome_engine.assign_holdout(records, 99, 20)
    assert first == second


def test_holdout_assignment_is_per_contact_not_per_payment():
    """
    One person with two failed payments must land wholly in one arm.
    Splitting them contaminates the lift estimate and means contacting
    someone whose other payment we are deliberately leaving alone.
    """
    from app.consent import contact_hash

    records = _dataset()
    held_out = outcome_engine.assign_holdout(records, 20260825, 20)

    by_contact = {}
    for record in records:
        digest = contact_hash(record["customer"]["phone"])
        arm = "control" if digest in held_out else "treated"
        by_contact.setdefault(digest, set()).add(arm)

    split = {d for d, arms in by_contact.items() if len(arms) > 1}
    assert not split, f"{len(split)} contact(s) appear in both arms"


def test_holdout_is_stratified_across_failure_classes():
    """
    Unstratified sampling at this size can put zero - or half - of a small
    class into control, which would make any per-class figure meaningless.
    """
    from app.consent import contact_hash

    records = _dataset()
    held_out = outcome_engine.assign_holdout(records, 20260825, 20)

    per_class = {}
    for record in records:
        digest = contact_hash(record["customer"]["phone"])
        bucket = per_class.setdefault(record["_failure_class"], {"n": 0, "held": 0})
        bucket["n"] += 1
        if digest in held_out:
            bucket["held"] += 1

    for failure_class, bucket in per_class.items():
        share = bucket["held"] / bucket["n"] * 100
        assert 5 <= share <= 40, (
            f"{failure_class}: {share:.0f}% held out, expected near 20%"
        )


def test_holdout_size_tracks_the_configured_percent():
    records = _dataset()
    held_out = outcome_engine.assign_holdout(records, 20260825, 20)

    from app.consent import contact_hash
    contacts = {contact_hash(r["customer"]["phone"]) for r in records}

    share = len(held_out) / len(contacts) * 100
    assert 15 <= share <= 25
