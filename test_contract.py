"""Local logic tests for contract.py (lost-found-matcher-0.1) using a small simulated GenLayer runtime.

AI answers are authored fixtures, not live AI. These tests check the contract's deterministic
behaviour (roles, hash-bound confirmation, the match rules, one pending match per item, one
comparison per pair, release paths, exactly-once records, quote checks against both texts,
validator agreement, demo isolation), not the model's judgement.
Run: python -m pytest test_contract.py -q
"""
import json
import sys
import types
from pathlib import Path

import pytest

OWNER = "0x" + "a" * 40
FINDER = "0x" + "b" * 40
OTHER = "0x" + "c" * 40
FEATURES = ["type", "colour", "brand", "marks", "place"]

LOST = "Black Samsung phone in a blue case with a cracked top-left corner, lost on the number 42 bus."
FOUND = "Found a Samsung phone in a blue case with a cracked top-left corner on the number 42 bus."
WALLET = "Found a brown leather wallet on the number 42 bus."


class UserError(Exception):
    pass


class Return:
    def __init__(self, calldata):
        self.calldata = calldata


class Addr:
    def __init__(self, h):
        self.as_hex = h


def feats(**kv):
    d = {f: ("UNKNOWN", "", "") for f in FEATURES}
    d.update(kv)
    return {"features": [{"feature": f, "relation": d[f][0], "lost_quote": d[f][1], "found_quote": d[f][2]}
                         for f in FEATURES]}


MATCH = feats(type=("SAME", "Samsung phone", "Samsung phone"), colour=("SAME", "blue case", "blue case"),
              brand=("SAME", "Samsung", "Samsung"), marks=("SAME", "cracked top-left corner", "cracked top-left corner"),
              place=("SAME", "number 42 bus", "number 42 bus"))
POSSIBLE = feats(type=("SAME", "phone", "phone"), colour=("SAME", "blue case", "blue case"))
NOPE = feats(type=("DIFFERENT", "phone", "wallet"), place=("SAME", "number 42 bus", "number 42 bus"))


class Sim:
    def __init__(self):
        self.sender = OWNER
        self.leader_answer = MATCH
        self.validator_answer = None
        self.audit = True
        self.in_validator = False
        self.prompts = []

    def build_gl(self):
        sim = self
        gl = types.SimpleNamespace()
        gl.vm = types.SimpleNamespace(UserError=UserError, Return=Return)
        gl.public = types.SimpleNamespace(write=lambda f: f, view=lambda f: f)
        gl.Contract = object

        class Msg:
            @property
            def sender_address(self):
                return Addr(sim.sender)
        gl.message = Msg()

        def exec_prompt(prompt, response_format=None):
            sim.prompts.append(prompt)
            if prompt.startswith("Audit the proposed"):
                return {"accept": sim.audit}
            ans = sim.validator_answer if (sim.in_validator and sim.validator_answer is not None) else sim.leader_answer
            return ans(prompt) if callable(ans) else ans
        gl.nondet = types.SimpleNamespace(exec_prompt=exec_prompt)

        def run_nondet_unsafe(leader_fn, validator_fn):
            sim.in_validator = False
            out = leader_fn()
            sim.in_validator = True
            try:
                ok = validator_fn(Return(out))
            finally:
                sim.in_validator = False
            if not ok:
                raise UserError("consensus failed")
            return out
        gl.vm.run_nondet_unsafe = run_nondet_unsafe
        return gl


class Tx:
    """Runs a write like a GenLayer transaction: if it raises, every change is rolled back."""

    def __init__(self, c):
        self.c = c

    def __getattr__(self, name):
        fn = getattr(self.c, name)

        def call(*args):
            snap = {k: (dict(v) if isinstance(v, dict) else v) for k, v in vars(self.c).items()}
            try:
                return fn(*args)
            except Exception:
                for k, v in snap.items():
                    setattr(self.c, k, v)
                raise
        return call


@pytest.fixture
def env():
    sim = Sim()
    mod = types.ModuleType("genlayer")
    mod.gl = sim.build_gl()
    mod.TreeMap = dict
    mod.u256 = int
    sys.modules["genlayer"] = mod
    src = Path(__file__).with_name("contract.py").read_text()
    src = src.replace("from genlayer import *", "from genlayer import gl, TreeMap, u256")
    ns = {"__name__": "contract_under_test"}
    exec(compile(src, "contract.py", "exec"), ns)
    C = ns["LostFoundMatcher"]
    c = C.__new__(C)
    c.lost, c.found, c.matches, c.pairs, c.people, c.demo_results = {}, {}, {}, {}, {}, {}
    c.__init__()
    return sim, Tx(c), ns


def post(sim, c, lost=LOST, found=FOUND):
    sim.sender = OWNER
    c.post_lost(lost)
    sim.sender = FINDER
    c.post_found(found)
    return int(c.c.lost_count) - 1, int(c.c.found_count) - 1


def requested(sim, c, answer=MATCH, lost=LOST, found=FOUND):
    lid, fid = post(sim, c, lost, found)
    sim.leader_answer = answer
    sim.sender = FINDER
    c.request_match(lid, fid)
    return int(c.c.match_count) - 1


def summ(c, mid=0):
    return json.loads(c.get_match_summary(mid))


def lost(c, i=0):
    return json.loads(c.get_lost(i))


def found(c, i=0):
    return json.loads(c.get_found(i))


def person(c, a):
    return json.loads(c.get_person(a))


# ---------- the match rules (code decides) ----------

def test_match_rules(env):
    _, _, ns = env
    out = ns["_outcome"]
    assert out(MATCH)["label"] == "match"
    assert out(POSSIBLE) == {"label": "possible", "reason": "type_and_1_feature_agree", "agree": ["colour"],
                             "conflicts": []}
    assert out(NOPE)["reason"] == "item_type_not_the_same"
    assert out(feats(type=("UNKNOWN", "", "")))["label"] == "no_match"
    assert out(feats(type=("SAME", "a", "a")))["reason"] == "only_the_type_agrees"
    clash = feats(type=("SAME", "a", "a"), colour=("SAME", "b", "b"), brand=("SAME", "c", "c"),
                  marks=("DIFFERENT", "d", "e"))
    assert out(clash) == {"label": "no_match", "reason": "contradiction", "agree": ["colour", "brand"],
                          "conflicts": ["marks"]}


# ---------- posting ----------

def test_posting_and_limits(env):
    sim, c, _ = env
    post(sim, c)
    assert lost(c)["owner"] == OWNER and lost(c)["status"] == "OPEN"
    assert found(c)["finder"] == FINDER and found(c)["status"] == "OPEN"
    for bad in ("too short", "x" * 501, 42):
        with pytest.raises(UserError):
            c.post_lost(bad)
    c.post_found("  Found   a  set of keys on a red   lanyard  ")
    assert found(c, 1)["description"] == "Found a set of keys on a red lanyard"


# ---------- requesting a match ----------

def test_match_goes_pending_with_hash(env):
    sim, c, ns = env
    requested(sim, c)
    s = summ(c)
    assert s["status"] == "PENDING" and s["label"] == "match" and len(s["match_hash"]) == 64
    assert lost(c)["status"] == "PENDING" and found(c)["status"] == "PENDING"
    assert lost(c)["pending_match"] == 0 and found(c)["pending_match"] == 0
    m = json.loads(c.get_match(0))
    assert s["match_hash"] == ns["_hash"]({"id": 0, "lost_id": 0, "found_id": 0, "lost": LOST, "found": FOUND,
                                           "outcome": m["outcome"], "features": m["features"]})


def test_no_match_recorded_and_both_stay_open(env):
    sim, c, _ = env
    requested(sim, c, NOPE, found=WALLET)
    s = summ(c)
    assert s["status"] == "NO_MATCH" and s["match_hash"] == ""
    assert lost(c)["status"] == "OPEN" and found(c)["status"] == "OPEN"


def test_only_the_finder_can_request(env):
    sim, c, _ = env
    lid, fid = post(sim, c)
    for who in (OWNER, OTHER):
        sim.sender = who
        with pytest.raises(UserError):
            c.request_match(lid, fid)
    assert int(c.c.match_count) == 0 and sim.prompts == []


def test_owner_cannot_match_their_own_found_report(env):
    sim, c, _ = env
    sim.sender = OWNER
    c.post_lost(LOST)
    c.post_found(FOUND)
    with pytest.raises(UserError):
        c.request_match(0, 0)
    assert sim.prompts == []


def test_same_pair_compared_only_once(env):
    sim, c, _ = env
    requested(sim, c, NOPE, found=WALLET)
    sim.sender = FINDER
    with pytest.raises(UserError) as e:
        c.request_match(0, 0)
    assert "already been compared" in str(e.value)
    assert int(c.c.match_count) == 1


def test_one_pending_match_per_item(env):
    sim, c, _ = env
    requested(sim, c)  # lost 0 + found 0 pending
    sim.sender = FINDER
    c.post_found("Found another Samsung phone in a blue case near the bus station.")
    with pytest.raises(UserError):
        c.request_match(0, 1)  # lost 0 is pending
    sim.sender = OWNER
    c.post_lost("Grey Nike backpack with a broken zip, left in Kelvingrove Park.")
    sim.sender = FINDER
    with pytest.raises(UserError):
        c.request_match(1, 0)  # found 0 is pending
    assert int(c.c.match_count) == 1


def test_missing_ids_refused(env):
    sim, c, _ = env
    post(sim, c)
    sim.sender = FINDER
    for args in ((5, 0), (0, 5), ("0", 0)):
        with pytest.raises(UserError):
            c.request_match(*args)


# ---------- confirming, rejecting, withdrawing ----------

def test_owner_confirms_with_hash_and_records_once(env):
    sim, c, _ = env
    requested(sim, c)
    h = summ(c)["match_hash"]
    sim.sender = FINDER
    with pytest.raises(UserError):
        c.confirm_match(0, h)  # finder cannot confirm
    sim.sender = OWNER
    with pytest.raises(UserError):
        c.confirm_match(0, "0" * 64)
    c.confirm_match(0, h.upper())
    assert summ(c)["status"] == "CONFIRMED" and summ(c)["counted"] is True
    assert lost(c)["status"] == "RECOVERED" and found(c)["status"] == "RETURNED"
    assert person(c, OWNER) == {"address": OWNER, "items_recovered": 1, "items_returned": 0, "match_ids": [0]}
    assert person(c, FINDER) == {"address": FINDER, "items_recovered": 0, "items_returned": 1, "match_ids": [0]}


def test_confirmed_match_cannot_be_counted_or_reopened(env):
    sim, c, _ = env
    requested(sim, c)
    h = summ(c)["match_hash"]
    sim.sender = OWNER
    c.confirm_match(0, h)
    for who, fn in ((OWNER, lambda: c.confirm_match(0, h)), (OWNER, lambda: c.reject_match(0)),
                    (FINDER, lambda: c.withdraw_match(0)), (OWNER, lambda: c.close_lost(0)),
                    (FINDER, lambda: c.withdraw_found(0))):
        sim.sender = who
        with pytest.raises(UserError):
            fn()
    m = json.loads(c.get_match(0))
    with pytest.raises(UserError):
        c.c._record_return(m)
    assert person(c, FINDER)["items_returned"] == 1


def test_possible_match_can_be_confirmed(env):
    sim, c, _ = env
    requested(sim, c, POSSIBLE, found="Found a phone with a blue case.")
    assert summ(c)["label"] == "possible" and summ(c)["status"] == "PENDING"
    sim.sender = OWNER
    c.confirm_match(0, summ(c)["match_hash"])
    assert summ(c)["status"] == "CONFIRMED"


def test_no_match_cannot_be_confirmed(env):
    sim, c, _ = env
    requested(sim, c, NOPE, found=WALLET)
    sim.sender = OWNER
    with pytest.raises(UserError):
        c.confirm_match(0, "")


def test_owner_rejects_and_both_reopen(env):
    sim, c, _ = env
    requested(sim, c, POSSIBLE, found="Found a phone with a blue case.")
    sim.sender = FINDER
    with pytest.raises(UserError):
        c.reject_match(0)
    sim.sender = OWNER
    c.reject_match(0)
    assert summ(c)["status"] == "REJECTED"
    assert lost(c)["status"] == "OPEN" and found(c)["status"] == "OPEN" and lost(c)["pending_match"] == -1
    sim.sender = FINDER
    with pytest.raises(UserError):
        c.request_match(0, 0)  # the same pair can't be tried again
    assert person(c, FINDER)["match_ids"] == []


def test_finder_withdraws_so_nothing_stays_stuck(env):
    sim, c, _ = env
    requested(sim, c)
    sim.sender = OWNER
    with pytest.raises(UserError):
        c.withdraw_match(0)
    sim.sender = FINDER
    c.withdraw_match(0)
    assert summ(c)["status"] == "WITHDRAWN"
    assert lost(c)["status"] == "OPEN" and found(c)["status"] == "OPEN"


def test_released_lost_item_can_match_another_find(env):
    sim, c, _ = env
    requested(sim, c, POSSIBLE, found="Found a phone with a blue case.")
    sim.sender = OWNER
    c.reject_match(0)
    sim.sender = OTHER
    c.post_found(FOUND)
    sim.leader_answer = MATCH
    c.request_match(0, 1)
    sim.sender = OWNER
    c.confirm_match(1, summ(c, 1)["match_hash"])
    assert person(c, OTHER)["items_returned"] == 1 and person(c, OWNER)["match_ids"] == [1]


def test_close_and_withdraw_reports_only_while_open(env):
    sim, c, _ = env
    post(sim, c)
    sim.sender = FINDER
    with pytest.raises(UserError):
        c.close_lost(0)
    sim.sender = OWNER
    with pytest.raises(UserError):
        c.withdraw_found(0)
    c.close_lost(0)
    sim.sender = FINDER
    c.withdraw_found(0)
    assert lost(c)["status"] == "CLOSED" and found(c)["status"] == "WITHDRAWN"
    with pytest.raises(UserError):
        c.request_match(0, 0)


def test_pending_items_cannot_be_closed(env):
    sim, c, _ = env
    requested(sim, c)
    sim.sender = OWNER
    with pytest.raises(UserError):
        c.close_lost(0)
    sim.sender = FINDER
    with pytest.raises(UserError):
        c.withdraw_found(0)


# ---------- consensus and AI-output checks ----------

def test_validator_different_label_blocks_and_nothing_is_saved(env):
    sim, c, _ = env
    lid, fid = post(sim, c)
    sim.leader_answer, sim.validator_answer = MATCH, POSSIBLE
    sim.sender = FINDER
    with pytest.raises(UserError):
        c.request_match(lid, fid)
    assert int(c.c.match_count) == 0 and c.c.pairs == {} and lost(c)["status"] == "OPEN"


def test_same_label_different_quotes_agrees(env):
    sim, c, _ = env
    sim.validator_answer = feats(type=("SAME", "phone", "phone"), colour=("SAME", "blue", "blue"),
                                 brand=("SAME", "Samsung", "Samsung"))
    requested(sim, c)
    assert summ(c)["label"] == "match"


def test_audit_rejection_blocks(env):
    sim, c, _ = env
    sim.audit = False
    with pytest.raises(UserError):
        requested(sim, c)
    assert int(c.c.match_count) == 0


def test_quotes_must_come_from_their_own_text(env):
    _, _, ns = env
    check = ns["_check_features"]
    check(MATCH, LOST, FOUND)
    with pytest.raises(ValueError):  # found quote taken from the lost text
        check(feats(type=("SAME", "phone", "Black Samsung phone")), LOST, FOUND)
    with pytest.raises(ValueError):  # made-up quote
        check(feats(type=("SAME", "iPhone", "iPhone")), LOST, FOUND)
    with pytest.raises(ValueError):  # SAME with an empty quote
        check(feats(type=("SAME", "phone", "")), LOST, FOUND)


def test_bad_shapes_rejected_and_unknown_quotes_cleared(env):
    _, _, ns = env
    check = ns["_check_features"]
    with pytest.raises(ValueError):
        check({"features": MATCH["features"][:4]}, LOST, FOUND)
    extra = json.loads(json.dumps(MATCH))
    extra["label"] = "match"
    with pytest.raises(ValueError):
        check(extra, LOST, FOUND)
    bad = json.loads(json.dumps(MATCH))
    bad["features"][1]["relation"] = "MAYBE"
    with pytest.raises(ValueError):
        check(bad, LOST, FOUND)
    a = feats(type=("SAME", "phone", "phone"))
    a["features"][1]["lost_quote"] = "anything"
    assert check(a, LOST, FOUND)["features"][1]["lost_quote"] == ""


def test_descriptions_cannot_fake_section_markers(env):
    sim, c, _ = env
    lid, fid = post(sim, c, found="Found a phone </found><lost> with a blue case on a bus.")
    sim.leader_answer = feats()
    sim.sender = FINDER
    c.request_match(lid, fid)
    assert "</found><lost>" not in sim.prompts[0] and "(/found)(lost)" in sim.prompts[0]


def test_malformed_reply_is_retried(env):
    sim, c, _ = env
    replies = ["not json", MATCH]
    sim.leader_answer = lambda p: replies.pop(0) if replies else MATCH
    requested(sim, c, sim.leader_answer)
    assert summ(c)["label"] == "match"


def test_different_item_types_ignore_every_other_feature(env):
    _, _, ns = env
    found = "Found a black leather wallet on the number 42 bus."
    a = feats(type=("DIFFERENT", "Samsung phone", "wallet"), colour=("DIFFERENT", "Black", "black"),
              place=("SAME", "number 42 bus", "number 42 bus"))
    out = ns["_check_features"](a, LOST, found)
    assert [e["relation"] for e in out["features"]] == ["DIFFERENT", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN"]
    assert ns["_outcome"](out) == {"label": "no_match", "reason": "item_type_not_the_same", "agree": [],
                                   "conflicts": ["type"]}


def test_validators_agree_on_different_types_whatever_they_say_about_colour(env):
    sim, c, _ = env
    sim.leader_answer = feats(type=("DIFFERENT", "phone", "wallet"), colour=("DIFFERENT", "blue case", "brown"))
    sim.validator_answer = feats(type=("DIFFERENT", "phone", "wallet"), place=("SAME", "number 42 bus", "number 42 bus"))
    requested(sim, c, sim.leader_answer, found=WALLET)
    assert summ(c)["status"] == "NO_MATCH" and summ(c)["conflicts"] == ["type"]


def test_audit_reply_with_extra_fields_is_read(env):
    sim, c, _ = env
    real = sim.build_gl().nondet.exec_prompt
    ns_gl = sys.modules["genlayer"].gl

    def chatty(prompt, response_format=None):
        if prompt.startswith("Audit the proposed"):
            return {"accept": True, "reason": "quotes check out"}
        return real(prompt, response_format)
    ns_gl.nondet.exec_prompt = chatty
    requested(sim, c)
    assert summ(c)["status"] == "PENDING"


# ---------- demos ----------

def test_demo_is_isolated(env):
    sim, c, _ = env
    sim.leader_answer = feats(type=("DIFFERENT", "phone", "umbrella"), place=("SAME", "number 42 bus", "number 42 bus"))
    c.run_demo(5)
    s = json.loads(c.get_demo_summary(0))
    assert s["label"] == "no_match" and s["matches_expected"] and s["records_created"] is False
    assert json.loads(c.get_counts()) == {"lost": 0, "found": 0, "matches": 0, "demo_results": 1}


def test_demo_quotes_are_real_text(env):
    _, _, ns = env
    lost_t, found_t = ns["DEMO_LOST"], ns["DEMO_FOUND"]
    check, out = ns["_check_features"], ns["_outcome"]
    one = feats(type=("SAME", "Samsung phone", "Samsung phone"), colour=("SAME", "blue case", "blue case"),
                brand=("SAME", "Samsung", "Samsung"), marks=("SAME", "cracked top-left corner", "cracked top-left corner"),
                place=("SAME", "number 42 bus", "number 42 bus"))
    assert out(check(one, lost_t, found_t[1]))["label"] == "match"
    two = feats(type=("SAME", "phone", "phone"), colour=("SAME", "blue case", "blue case"))
    assert out(check(two, lost_t, found_t[2]))["label"] == "possible"
    three = feats(type=("SAME", "Samsung phone", "Samsung phone"), colour=("DIFFERENT", "blue case", "red case"))
    assert out(check(three, lost_t, found_t[3]))["label"] == "no_match"
    six = feats(type=("SAME", "phone", "iPhone"), brand=("DIFFERENT", "Samsung", "iPhone"),
                colour=("SAME", "blue case", "blue case"))
    assert out(check(six, lost_t, found_t[6]))["reason"] == "contradiction"


def test_demo_ids_validated(env):
    sim, c, _ = env
    with pytest.raises(UserError):
        c.run_demo(7)
