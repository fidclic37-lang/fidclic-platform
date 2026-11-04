# Product

FidClic is a loyalty platform for French cafés, restaurants and local shops. Internal
identifiers still say `fidelitour`. Do not rename them.

## Who uses it

| Role | In code | What they do |
|---|---|---|
| Customer | `user` | Holds a digital card on their phone, collects visits and rewards, receives offers |
| Staff | `staff` | Scans cards at the counter, within the rights the owner gave them |
| Owner | `business_owner` | Designs the card, manages customers, campaigns, automations, analytics and billing |
| FidClic team | `super_admin` | Runs the platform |

## Journeys that must never break

1. A customer signs up, gets the card and adds it to their phone.
2. Staff scan a card, the visit counts once, and the reward unlocks at the right visit.
3. A customer claims a reward once and only once.
4. An owner sends a campaign to the right people, once, respecting their consent.
5. An owner sees figures that match what actually happened.

## Rules that hold everywhere

- One shop or store never sees or changes another's data.
- A person only sees what their role and page rights allow.
- Real data always wins over demo data.
- The interface speaks French first. The FidClic wordmark is never translated.
- Customers are mostly on phones.

## Decisions belong to the user

Do not decide pricing, plan contents, reward rules, what customers receive, approved
wording or legal claims. Propose, then let the user decide.
