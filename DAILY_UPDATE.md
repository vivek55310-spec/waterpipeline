# Keeping the portal current — the daily routine

The portal is only as good as the last entry made in it. This is the part that
decides whether the AI answers are worth anything, because the assistant reads the
live data and nothing else.

## How updating works

There is **one copy** of the data, on the server. Nobody sends files around.

1. A person opens the address and signs in with their own user ID.
2. They type into the boxes on any tab. There is no Save button — the moment a box
   loses focus, the change goes to the server and everyone else's screen picks it up
   within half a minute.
3. Every change is stamped with **who** made it and **when**, and written to the
   change log at the bottom of Settings & data — field by field, old value → new value.
4. If two people edit at the same instant, the second save is refused, that person's
   page reloads the newer copy and they re-enter their line. Nothing is silently
   overwritten.

Because the record shows the name against each change, it is worth giving every
person their own user ID rather than sharing one.

## Who updates what

| Tab | Who normally fills it | When |
|---|---|---|
| **Mainline DPR** | site engineer | every evening — the day's metres/joints against each activity |
| **HDD** and **SHDD** | HDD in-charge | on the day a stage moves (pilot, reaming, pulling) |
| **Civil work** | civil engineer | when a chamber stage finishes |
| **Documentation** | office assistant / document controller | when a document is submitted, commented, resubmitted or approved |
| **Pre-project activities** | site officer | when an item completes or a target date slips |
| **Quantities (BoQ)** | quantity surveyor / billing | when a measurement is taken or an anticipated quantity changes |
| **Settings & data** | you (admin) | rarely — rules, weightages, users |

## The five-minute evening routine

Whoever is on site duty does this before leaving:

1. **Mainline DPR** → add today's line: the activity, today's quantity, remarks. The
   cumulative figure and the weighted progress percentage compute themselves.
2. **HDD / SHDD** → for any crossing that moved, change the stage figure (0 to 1, so
   half-done reaming is `0.5`). The date of last update sets itself, which is what
   the "no update for N days" rule watches.
3. **Documentation** → move any document that changed stage, and paste the OneDrive
   or SharePoint **share link** into its link box. The portal stores the link only,
   never the file, so file permissions stay where IT put them.
4. **Focus list** → look at what turned red. Anything there is either overdue, over
   the quantity threshold, stuck in review, or working without a permission or an
   approved drawing.
5. **AI assistant → Today's summary** → it writes the DPR summary from what was just
   entered. Read it, correct anything that reads wrong (which usually means an entry
   is wrong), and circulate.

## Where the AI answers come from

The assistant has no memory and no outside knowledge of your project. Each time you
ask, the portal takes the **current** data from your screen, squeezes it into a
compact form, and sends that along with your question to Gemini. So:

* An entry made a minute ago is already in the answer.
* Something never entered does not exist as far as the assistant is concerned — it
  will say so rather than invent a figure.
* Nothing is sent to Google unless somebody presses a button. The key lives on the
  server; no browser ever sees it.

The portal does not send the whole project on every question — that would blow
through a free-tier limit quickly. It sends the sections the question needs:
"which HDD crossings have no approved drawing?" sends the crossings, not the BoQ.
The line under each answer tells you roughly how many tokens went out and how much of
the day's allowance is used.

Questions worth asking:

* *which crossings have no approved drawing but work has started?*
* *draft a letter to the contractor for documents pending more than 15 days*
* *which BoQ items are more than 10 % over the work-order quantity, with the money?*
* *what is stopping the NH crossing from starting?*
* *write a one-page brief for the GM on where the project stands*

## Monthly housekeeping (admin)

* **Settings & data → Download full backup** — keep the file on the office drive.
* Check the **Users** list and remove anybody who has moved on.
* Glance at the **change log**. Days with no entries are the days the portal drifted
  away from the site; that is a supervision matter, not a software one.
* Check the AI counter on the assistant tab. If you are near the daily cap most days,
  raise `AI_DAILY_LIMIT` — and watch that the free Gemini quota can carry it.
