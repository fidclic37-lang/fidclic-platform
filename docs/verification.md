# Verification

How to know a change works. A loop is only as honest as this file.

## Where testing may happen

| Place | Data | Use it for |
|---|---|---|
| Local (`scripts/dev_local.py`) | In-memory demo data, gone on restart | All testing, by Claude and by hand |
| Vercel preview | **The production database** | Looking only. Never create, edit, scan or send |
| Production (`app.fidclic.com`) | Live merchants | Nothing, unless the user asks |

`MONGODB_URI` is set for both Production and Preview on Vercel, so a preview URL
reads and writes real merchant data. Pentests and load runs are local only.

## Automated checks

Run from the repository root. `api` and `e2e` are the required CI checks.

| Check | Command | What it proves | Time |
|---|---|---|---|
| One API test | `cd api && python3 tests/test_x.py` | That feature, through the real endpoints on mongomock | Seconds |
| API tests matching a name | `python3 scripts/run_api_tests.py x` | A family of tests | Varies |
| All API tests (CI `api`) | `python3 scripts/run_api_tests.py` | Nothing else broke | About 20 min |
| Frontend build | `npx vite build` | The app compiles. It does not prove the feature works | Seconds |
| One browser test | `npx vite build && npx playwright test e2e/x.spec.js` | A real browser walks the path on a phone viewport | Minutes |
| All browser tests (CI `e2e`) | `npx vite build && npm run e2e` | Customer journeys still work | About 12 min |
| AI answers (CI `golden`) | Add the `ai` label to the pull request | Known questions still grade correctly | Only with the label |

Use the local Chrome for browser tests with `PW_CHANNEL=chrome`. The machine has
8 GB of memory, so run the narrow check while working and let CI run everything.

API tests are standalone scripts that exit non-zero on failure. The runner
fails if a test it does not know about breaks.

## How every build is done

1. Write the failing test first and watch it fail.
2. Cover the edge cases: empty, zero, one, limits, wrong input, time zones, DST, multi-store.
3. Add an integration test through the real endpoints in `api/tests/`, and a
   Playwright test in `e2e/` when there is a screen.
4. Never delete a failing test, loosen an assertion, skip a check or change
   expected behaviour just to get a pass. If a test looks wrong, explain why and ask.

## Local browser check

```bash
npx vite build
python3 scripts/dev_local.py
```

Open `http://localhost:8765`. Check the routes in the task at phone width (390 px)
and desktop width (1440 px), including the loading, empty, success and error states.

## Reporting

Every criterion gets exactly one of these, with the output that shows it:

- **PASS**: ran and succeeded.
- **FAIL**: ran and failed.
- **NOT RUN**: not run, and why.
- **BLOCKED**: a prerequisite is missing, and which one.

A green build is not a working feature. "It should work" is NOT RUN.
