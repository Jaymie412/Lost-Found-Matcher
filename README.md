# Lost & Found Matcher

A GenLayer Intelligent Contract that answers: **is the thing someone found the thing someone else lost?**

Anyone can post a lost report or a found report, so there are two open pools. A finder asks the contract to compare their found report with one lost report. GenLayer validators compare the **two descriptions side by side**, feature by feature (item type, colour, brand, distinctive marks, place), quoting **both** texts word for word. **Code** checks the quotes and decides `match`, `possible` or `no_match`. A match is held as pending until the owner confirms it is theirs, bound to a `match_hash`, or rejects it. A confirmed return is added once to both people's records.

Example: "Black Samsung phone in a blue case with a cracked top-left corner, lost on the number 42 bus" and "Found a Samsung phone in a blue case with a cracked top-left corner on the number 42 bus" give a `match`. The same find in a **red** case gives `no_match`, because colour contradicts.

## Why I built it

Lost-and-found boards are full of near-misses: "found a phone" posts that could be anyone's, and owners who never see the right post. Comparing descriptions feature by feature, with a clear rule for contradictions, helps the right two people meet, and every decision points to the exact words both people wrote.

## How it works

| Step | Who | Method | Result |
|---|---|---|---|
| Post a lost report | Owner | `post_lost(description)` | lost_id, OPEN |
| Post a found report | Finder | `post_found(description)` | found_id, OPEN |
| Ask for a comparison | Finder of that found report | `request_match(lost_id, found_id)` | `match` or `possible` → PENDING with `match_hash`; `no_match` → recorded, both stay OPEN |
| Confirm it is theirs | Owner of that lost report | `confirm_match(match_id, expected_match_hash)` | CONFIRMED: lost RECOVERED, found RETURNED, records updated once |
| Or reject it | Owner | `reject_match(match_id)` | REJECTED: both reports OPEN again |
| Or withdraw it | Finder | `withdraw_match(match_id)` | WITHDRAWN: both reports OPEN again |
| Close a report | Owner / finder | `close_lost(lost_id)` / `withdraw_found(found_id)` | only while OPEN |

Read methods: `get_match_summary`, `get_match`, `get_lost`, `get_found`, `get_person(address)`, `get_counts`, `get_policy`, `get_demo`, `get_demo_result`, `get_demo_summary`. Demo write: `run_demo(case_id)`.

## Match rules (code)

Each feature is `SAME`, `DIFFERENT` or `UNKNOWN`.

| Result | Rule |
|---|---|
| no_match | item type is not SAME, **or** any feature is DIFFERENT (a contradiction) |
| match | type SAME, no contradiction, and 2 or more of colour, brand, marks, place are SAME |
| possible | type SAME, no contradiction, and exactly 1 of them is SAME |
| no_match | type SAME but nothing else agrees |

When the item types differ, code ignores every other feature (the colour of a wallet isn't compared with the colour of a phone).

Both `match` and `possible` can be confirmed or rejected by the owner; `no_match` can't.

## How it stays fair

| Risk | How the contract handles it |
|---|---|
| Someone claiming a find for an item they didn't lose | Only the owner of the lost report can confirm, and only with the exact `match_hash` of that comparison. |
| An owner "finding" their own item | The finder and the owner must be different addresses. |
| Trying pairs over and over until the AI says yes | Each lost/found pair can be compared only once. |
| One item matched to two people at once | An item with a pending match can't be compared, closed or withdrawn until that match is confirmed, rejected or withdrawn. |
| A match left pending forever | The owner can reject and the finder can withdraw at any time; both reports reopen. There are no deadlines. |
| Counting a return twice | One internal method updates records. It refuses a match already counted (a flag on the match, plus `match_ids` on both people). |
| The AI making things up | Every SAME or DIFFERENT needs a quote from each text, and code checks each quote appears in its **own** text. The AI never decides the result; code does. |
| Instructions hidden in a description | Descriptions are treated as data and can't fake the section markers. Validators audit the leader's answers for signs that hidden instructions were followed. |

## How consensus works

Using `gl.vm.run_nondet_unsafe`, the leader compares the two descriptions. Each validator compares them independently, checks the leader's answers against the same strict rules, and must reach the **same result** (`match`, `possible` or `no_match`). It then runs an AI audit of the leader's quotes and relations, returning `{"accept": true/false}`. Nothing is stored until all of this passes. A malformed AI reply is asked again, up to 3 times. No web pages are fetched, so the only evidence is what the two people wrote.

## Quick start in Studio

1. Import `contract.py` into GenLayer Studio and deploy. There are no parameters.
2. Call `run_demo` with `case_id = 1` and wait for it to finish.
3. Call `get_demo_summary` with `result_id = 0`. Expected: label `match`, `matches_expected: true`, `records_created: false`.

See [DEMO_GUIDE.md](DEMO_GUIDE.md) for all six demos and the live walkthrough.

## Demonstrated in Studio

See [DEMO_RESULTS.md](DEMO_RESULTS.md) for the recorded run, deployment address and screenshots.

## Testing

`test_contract.py` contains 31 local tests using a simulated GenLayer runtime and authored AI answers. See [VERIFICATION.md](VERIFICATION.md).

## Boundaries

- It compares what two people wrote. It can't see the item or prove who owns it; the owner's confirmation is what closes a match.
- A vague description gives a weak result. Two items that really match can come out `possible` or `no_match` if one person leaves details out.
- Arranging the hand-over happens off-chain.
- All data is public on-chain. Don't put names, phone numbers, addresses or other personal details in a description.
- Instructions hidden in a description are treated as data. This reduces prompt injection but doesn't guarantee against it.
- Different addresses don't prove different people.

## Built with

- [GenLayer](https://docs.genlayer.com) Intelligent Contracts (Python, GenVM v0.2.16 runner)
- Developed with help from Claude
