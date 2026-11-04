# Task: Équipe & accès only shows and changes the stores the viewer should reach

This repository is public. No customer data, passwords, keys or merchant details here,
and no details of an unfixed security hole: `new-task` keeps those specs outside the repo.

## Goal
In Paramètres › Équipe & accès, the invite form offers only the store open in the menu,
and « Accès par établissement » shows a non-owner only their own store and who has access
there. Only an owner login sees every store. The API enforces the same limits as the screen.

## Why
A merchant with several stores saw every store while one was open, in the very section
that hands out access. A non-owner must never reach another store's team.

## How to reproduce
1. Owner login on a shop with three stores, one store open in the menu.
2. Paramètres › Équipe & accès, form « Inviter un utilisateur »: all three stores are offered.
3. Non-owner login given two of the three, one open: both are offered, and the row of a
   person who also works in the other one shows that other store.

## Words used here
- **Open store**: the one store named by the `X-FidClic-Store` header or `?store=`.
  `all`, an empty value or nothing names no store, and `all` never widens a named one.
- **Own stores**: the open stores an account was given (`team_access._covered`).
- **Non-owner**: administrateur, manager, staff given team rights, or a custom role.

## Decisions taken from the brief
- Owner with one store open: the invite form offers that store only. Every other part of
  the section still reaches every store, so a second store is given afterwards from
  « Accès par établissement » or the user's row.
- Multi-store non-owner with one store open: that store only. Naming no store (`all`): all
  their own stores and never another (the rule already in `store_scope.py`).
- The menu no longer offers « all stores » on screen, but `all` is what the API receives
  with nothing chosen, so it is covered.
- Account-level actions on a person who works in the open store (new password, switching
  off, delete) stay allowed, because that person is in the viewer's store and team.
- A role change is refused from one open store when the person also works in another,
  because it would change their rights there too.

## In scope
- `api/features/team_access.py`: the `/api/owner/team-access*` endpoints.
- `api/server.py`: the older `/api/owner/team*` endpoints stay owner-only.
- `src/pages/EquipeAccesPage.jsx`: the invite form and « Accès par établissement ».
- New tests in `api/tests/` and `e2e/`.

## Out of scope
- Who is visible by role: a non-owner still sees only themselves and accounts below them.
  Nothing is widened to show the owner or peers to a non-owner.
- What counts as covered for accounts created before stores existed (`_covered`).
- `store_scope.resolve`, which other pages share and which falls back rather than refuses.
- Other sections and endpoints: Sécurité, `/api/owner/branches`, employee links. Problems
  found there go in the report, not in this change.
- The design, the wording of existing labels, plan limits, role templates.

## Acceptance criteria

### Invite form
- [ ] AC1. Owner, store A open: `invite_stores` holds only A, and the form offers only A, already chosen.
- [ ] AC2. Owner, nothing open (`all`): `invite_stores` holds every store.
- [ ] AC3. Non-owner given A and B, A open: `invite_stores` holds only A. Naming no store: A and B, never C.
- [ ] AC4. Manager of A: `invite_stores` holds only A, whatever the role being invited.
- [ ] AC5. Non-owner, A open, invite with `branch_ids` holding B or C: 403, and no account is created.
- [ ] AC6. Non-owner, A open, invite to A: created, with A only.
- [ ] AC7. Non-owner with no store left: `stores` and `invite_stores` are empty, the screen
      says so and shows no form, and an invite is refused.

### Accès par établissement
- [ ] AC8. Non-owner given A and B, A open: `stores` holds only A, and `users`, `all_users` and
      `pending` hold only people with access to A.
- [ ] AC9. Same viewer: no row names another store. A person on A and B shows only A in
      `branch_ids`, `stores_label`, `perms` and `permissions`.
- [ ] AC10. Non-owner naming no store: only their own stores, and only people inside them.
- [ ] AC11. Owner, any store open: `stores` and `all_users` still hold everything, and the screen starts on the open store.
- [ ] AC12. Screen, non-owner with one store: a store name instead of a list to choose from, and no other store's name on the page.

### The API refuses
- [ ] AC13. Non-owner naming a store that is not their own, in the header or in `?store=`, on any
      `/api/owner/team-access*` request: 403, and nothing is read or changed.
- [ ] AC14. Two different stores named (header against `?store=`, or repeated values): refused
      for a non-owner, whichever of the two is their own, and nothing changes.
- [ ] AC15. `all` beside a named store never widens: it behaves as that store.
- [ ] AC16. Non-owner, A open, giving or taking B through
      `PUT /stores/B/users/{id}`: 403. Naming no store, with a store that is not their own, on or off: 403.
- [ ] AC17. Non-owner, A open, on a person who is only in B (edit, status, password, delete, give A): 403 with nothing changed.
- [ ] AC18. Non-owner, A open, editing a person on A and B: `branch_ids` naming B or C is 403. Sending only
      A keeps B, and B's permissions stay as they were even if the body sends others. Taking A away keeps B.
- [ ] AC19. Non-owner, A open, changing the role of a person on A and B: 403 with nothing changed. The same change with no store named works.
- [ ] AC20. The older `/api/owner/team*` endpoints answer an owner only, including for a non-owner with team rights who covers every store.
- [ ] AC21. Another shop's store id is refused for a non-owner, and ignored for that other shop's owner as today.
- [ ] AC22. Covered for administrateur, manager, staff given team rights, custom role; and for single-store and multi-store accounts.

### Nothing else moves
- [ ] AC23. Owner flows still work: creating, moving and removing across stores, with or without one open. The existing team tests still pass unchanged.
- [ ] AC24. A one-store shop works as before, with `main` or a leftover store id for its owner.
- [ ] AC25. Browser, phone (390 px) and desktop (1440 px): the owner path and the non-owner path both show the limits above and save.

## Verification
```bash
cd api && python3 tests/test_team_access_own_store.py
python3 scripts/run_api_tests.py team
python3 scripts/run_api_tests.py role
npx vite build && PW_CHANNEL=chrome npx playwright test e2e/equipe-own-store.spec.js
```

Browser path on the local server only: `/dashboard/parametres/equipe`, tabs « Utilisateurs » and
« Accès par établissement ». Never a Vercel preview, which uses the production database.

## Stop and ask
- The required behaviour is ambiguous, or the fix means a product decision.
- A new dependency, a schema change or a data migration is needed.
- It needs production data or production access.
- The same failure survives three different attempts.
- An existing test expects the opposite of this spec.

## Human test
Local server pe karo: `npx vite build`, phir `python3 scripts/dev_local.py`, phir `http://localhost:8765`.

1. Owner se login karo aur menu mein ek store kholo.
2. Paramètres › Équipe & accès kholo. « Inviter un utilisateur » mein sirf wahi store dikhna chahiye, aur already chuna hua.
3. « Accès par établissement » tab kholo. Owner ko list mein saare stores dikhne chahiye, aur list khuli hui store pe shuru honi chahiye.
4. Ab ek naya administrateur banao jo sirf ek store ka ho. Jo password dikhe, usse copy karo.
5. Logout karke us administrateur se login karo.
6. Invite form mein sirf uska store dikhna chahiye. « Accès par établissement » mein sirf uska store ka naam aur uske log dikhne chahiye. Doosre store ka naam kahin nahi hona chahiye.
7. Ek employé invite karke dekho. Account usi store mein banna chahiye.

## Completion evidence
Changed files, checks run with results, subagent findings and what happened to
them, remaining risks, the pull request, and the merge gate verdict.
