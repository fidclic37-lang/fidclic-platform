# Loop guide

Tum kaam batate ho, Claude spec banata hai, khud banata aur check karta hai, aur
PR tak le jaata hai. Tum sirf decisions aur final human test karte ho.

## Roz ka tareeka

1. Claude app mein naya session kholo. Folder **`fidelitour-deploy`** chuno, `website_antiG` nahi.
2. Prompt box ke neeche **Worktree** on karo aur mode **Auto** rakho.
3. Likho:

   ```text
   /new-task caisse pe scan ke baad reward do baar mil raha hai
   ```

4. Claude code check karke `docs/tasks/<naam>.md` banayega, zaroori sawaal poochega,
   aur ek `/goal ...` line dega. Use paste kar do.
5. Ab loop chalega. Beech mein kuch karne ki zaroorat nahi.
6. End mein teen mein se ek hoga:
   - **Merged:** safe tha, checks pass hue, production pe chala gaya.
   - **Review:** Claude batayega kyun, aur human test steps dega. Test karke "merge kar do" bolo.
   - **Stuck:** Claude batayega kya chahiye.

Kai bugs ek saath ho toh har bug ka alag session lo, sabme Worktree on.

## Spec mein kya hota hai

Socho tum ghar ka renovation contractor ko de rahe ho.

| Spec ka hissa | Ghar wala example | Kyun zaroori |
|---|---|---|
| **Goal** | "Kitchen mein paani leak band ho" | Kaam ka asli matlab |
| **How to reproduce** | "Nal kholo, sink ke neeche paani girta hai" | Bina dekhe andaaze se fix nahi hoga |
| **In scope** | "Sirf kitchen ki plumbing" | Kaam ki boundary |
| **Out of scope** | "Tiles mat badalna" | Warna contractor apni pasand se sab badal dega |
| **Acceptance criteria** | "Nal 10 min chalao, ek boond nahi gire" | Done ka matlab sabke liye same |
| **Verification** | "Pressure gauge se naapo" | Sirf "ho gaya" bolna proof nahi hai |
| **Stop and ask** | "Deewar todni pade toh pehle call karo" | Bade decisions tumhare rehte hain |
| **Human test** | "Khud nal khol ke dekho" | Final judge tum ho |

Sabse zaroori hain **acceptance criteria**. "Reward sahi kaam kare" kharab hai, kyunki
check nahi ho sakta. "Ek reward do baar claim karne par doosri baar error aaye aur points
na katein" achha hai.

## Team

Jis Claude ne kaam kiya wahi apna kaam pass kare, toh ye student ka apni copy check
karne jaisa hai. Isliye har inspector fresh aankhon se dekhta hai.

| Subagent | Real life mein | Kya dhoondta hai |
|---|---|---|
| `reviewer` | Senior engineer | Spec poora hua? Code sahi aur simple hai? |
| `bug-hunter` | Quality inspector | Edge cases, double counting, time zones, galat numbers |
| `error-handling-auditor` | Fire safety officer | Kuch fail ho toh user ko kya dikhega? Data bachega? |
| `security-auditor` | Bank ka security tester | Doosri shop ka data, bina login access, tampering |
| `browser-tester` | Mystery shopper | Asli browser mein phone size pe chala ke dekhna |
| `load-tester` | Rush hour simulation | Hazaaron users pe kya slow ya double hota hai |
| `improver` | Experienced mentor | Chhote simplifications. Product decisions nahi |

Inspectors sirf report karte hain. Fix main loop karta hai, phir dobara check hota hai.
Security aur load ki findings sirf report hoti hain, aur fix ka decision tumhara hai.

## Merge kab hota hai

Airport security jaisa socho. [Merge policy](merge-policy.md) ke hisaab se chhote backend
fixes jinke checks pass hain seedha nikal jaate hain. Paisa, login, Wallet, customer
messages aur screen pe dikhne wali cheezein tumhare paas aati hain.

## Human test

- **Local pe karo:** `npx vite build`, phir `python3 scripts/dev_local.py`, phir `http://localhost:8765`.
- **Preview URL pe sirf dekho.** Preview production database use karta hai, toh wahan
  scan, edit ya send mat karna.
- **Bug mile toh** PR ke session mein normal words mein likh do. Loop wahi se aage badhega.

## Loop kab mat chalao

- Kaam taste ka ho, jaise "website premium banao". Pehle measurable banao, ya khud saath baith ke karo.
- Business rule abhi decided nahi hai, jaise plan ki price.
- Production abhi down hai. Tab tum saath raho.

## Controls

| Command | Kaam |
|---|---|
| `/goal` | Status, turns aur token spend |
| `/goal clear` | Loop roko |
| Koi bhi message | Loop ko beech mein direction do |
