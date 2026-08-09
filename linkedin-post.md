# Kaza — LinkedIn post drafts

Live: https://yonabornstein.pythonanywhere.com/ · Code: github.com/yonabo111-cpu/kaza

## Option A — full version (recommended)

My roommates and I kept having the same three conversations on loop:

"Did anyone pay the electricity?"
"I think I still owe you from the groceries?"
"Whose turn is the trash?"

So I built Kaza. It's live, and you can try it right now.

It's a household app for people sharing an apartment. One person creates a household, everyone else joins with a 6-character code, and the whole mess lives in one place:

→ Shared expenses that split equally, personally, or per-person — with a settle-up that carries unpaid debt into the next month and tells you the fewest transfers needed to clear it

→ A shared shopping list where the items you check off turn into a split expense in one click

→ Recurring bills (rent, water, internet) that create the expense automatically when you mark them paid

→ Chores that rotate — hitting "done" passes the turn to the next roommate

→ A private ledger only you can see, so your own spending never shows up in anyone else's totals

My favorite part: you type "בא לי פסטה בולונז" or "i feel like ramen" and it hands you the ingredients to add to the list. 250+ dishes are built in and work offline; anything else it figures out with Claude.

No app store needed — open it in your phone's browser and install it straight to your home screen. It opens like a normal app from there. Hebrew, RTL, mobile-first, dark mode.

Under the hood: Flask + vanilla JS, 158 tests, MIT licensed, and self-hostable with one Docker command if you'd rather run your own.

It works and I use it every week. What I don't know is what breaks when someone who isn't me touches it.

So: if you share an apartment — or ever did — try it and tell me what's confusing, what's missing, and what you'd never use. Especially that last one.

👉 https://yonabornstein.pythonanywhere.com/
Code: github.com/yonabo111-cpu/kaza

#buildinpublic #flask #python #opensource

---

## Option B — short version

I got tired of the "did you pay the electricity / do I owe you for groceries / whose turn is the trash" loop with my roommates, so I built an app for it. It's live — you can open it right now.

Kaza: shared expenses with automatic settle-up, budgets, a shopping list that turns into an expense when you check things off, recurring bills, rotating chores, and a private ledger nobody else can see. Type "בא לי פסטה" and it adds the ingredients to the list.

No download, no app store — open it in your phone's browser and install it to your home screen. Hebrew, mobile-first, dark mode.

It works. Now I want to find out how it breaks for someone who isn't me — if you share an apartment, try it and tell me what's annoying about it.

👉 https://yonabornstein.pythonanywhere.com/
Code: github.com/yonabo111-cpu/kaza

#buildinpublic #opensource #python

---

## Posting notes

- LinkedIn cuts off after ~3 lines before "see more" — the opening three lines are doing the heavy lifting, keep them first.
- Attach `docs/screenshots/demo.gif` or `dashboard.png` as the post image. Posts with a visual get meaningfully more reach, and the GIF shows the settle-up recompute better than any sentence.
- LinkedIn suppresses posts with outbound links. Best reach: drop both links from the body, end with "link in the first comment," and post them as your own first comment right after publishing.
- Since people will land on a live site: make sure signup works cleanly from a cold start, and consider a demo account in the first comment for anyone who doesn't want to register.
- Reply to every comment in the first hour or two; it's the single biggest lever on how far the post travels.
