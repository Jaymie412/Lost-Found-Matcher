# Lost & Found Matcher verification

Contract file: `contract.py`, version `lost-found-matcher-0.1`.

## Local checks completed

- Python syntax compilation succeeded.
- `test_contract.py`: **31 tests passed** with `python -m pytest`, against a simulated GenLayer runtime. The test runner rolls back every change when a write fails, like a real GenLayer transaction.
- The contract uses only GenLayer SDK calls that my earlier contracts ran end to end on GenLayer Studio with the same `py-genlayer` runner (`gl.vm.run_nondet_unsafe`, `gl.vm.Return`, `gl.nondet.exec_prompt`, `gl.vm.UserError`, `gl.message.sender_address`). It makes no web requests.
- Every storage write in `request_match` happens after the validators have agreed.

All AI answers in the tests are authored fixtures. They check the contract's deterministic behaviour, not the AI's judgement.

## What the tests cover

**Match rules (code decides)**
1. All SAME → match; type + 1 → possible; type different or unknown → no_match; only the type → no_match; any DIFFERENT → no_match (contradiction), even with other agreements.

**Posting**
2. Reports store the right owner or finder; length and type limits; extra spaces are tidied.

**Requesting a match**
3. A match goes PENDING with a 64-character hash covering both texts, the outcome and the features; both reports are marked PENDING.
4. A no_match is recorded with no hash, and both reports stay OPEN.
5. Only the finder of that found report can request; the owner and outsiders are refused before the AI runs.
6. An owner can't match their own found report.
7. The same pair can be compared only once.
8. An item with a pending match can't be compared with anything else.
9. Missing or badly typed ids are refused.

**Confirming, rejecting, withdrawing**
10. Only the owner can confirm, only with the exact hash (case ignored); confirmation sets RECOVERED and RETURNED and updates both records once.
11. After confirmation, confirm, reject, withdraw, close and a direct internal replay are all refused; the record stays at one.
12. A `possible` match can be confirmed; a `no_match` can't.
13. Only the owner can reject; both reports reopen; the same pair can't be tried again.
14. Only the finder can withdraw; both reports reopen.
15. After a rejection, the lost item can match a different find from another person.
16. Reports can be closed or withdrawn only by their author and only while OPEN, and can't be matched afterwards.
17. Pending items can't be closed or withdrawn.

**Consensus and AI-output checks**
17a. When the item types differ, code sets every other feature to UNKNOWN, so validators that compare colours or places differently still agree.
17b. An audit reply with extra fields (such as a reason) is still read correctly.
18. A validator reaching a different result blocks the transaction and nothing is saved.
19. Validators quoting different words but reaching the same result still agree.
20. A failed audit blocks the transaction.
21. Each quote must come from its own text: a found quote taken from the lost text, a made-up quote, or a missing quote is rejected.
22. Missing or extra features, extra fields and unknown relations are rejected; quotes on UNKNOWN answers are cleared.
23. A description can't fake the section markers; a malformed AI reply is asked again.

**Demos**
24. Demos create no reports, matches or records; the demo quotes are real text and give the expected results.

## Live Studio evidence

See [DEMO_RESULTS.md](DEMO_RESULTS.md).
