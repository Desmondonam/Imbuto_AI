# Talk run sheet

*Turn an AI model into an application*. Friday 6 November 2026, 14:15 to 15:15, Olivia University,
Bujumbura, Track A.

Everything runs on your laptop, so the demo does not depend on venue Wi-Fi.

## Before you travel

- [ ] Export the deck to PDF and PowerPoint, and keep both offline
- [ ] Rehearse once with a timer
- [ ] Ask a Kirundi speaker to check the `rn` text, or say on stage that it is unreviewed
- [ ] Push the repository and make it public, or remove the GitHub link from the last slide
- [ ] Decide on Docker: install it and practise, or describe it without running it live

## One hour before

```bash
cd Imbuto_AI
rm -f data/imbuto.sqlite*        # clear old monitoring data
.venv/bin/uvicorn imbuto.api.main:app --factory --port 8000
```

Open these tabs: `/simulator?lang=en`, `/photo`, `/api/docs`, `/dashboard`, `/ops`.
Have two photos ready to upload: a bean leaf, and something that is not a leaf. Turn off sleep and
notifications. Set the browser zoom so that the back row can read it.

## Timing

| Minutes | Slides | Content |
| --- | --- | --- |
| 0 to 6 | 1 to 6 | Hello, the room's question, Burundi's constraints |
| 6 to 13 | 7 to 11 | Imbuto AI, five steps, architecture, data |
| 13 to 20 | 12 to 16 | Steps 1 and 2: package and API |
| 20 to 26 | 17 to 19 | Step 3: interface and 2G budget |
| 26 to 34 | 20 | Live demo |
| 34 to 40 | 21 to 23 | Steps 4 and 5: container and monitoring |
| 40 to 45 | 24 to 25 | The model we refused to ship |
| 45 to 48 | 26 to 29 | What is not done, the ask, teaching, close |
| 48 to 60 | 29 | Questions |

If you run late, cut slides 11 and 16 first.

## Live demo, 8 minutes

Start the traffic in a terminal as you begin, because it takes 2.5 minutes:

```bash
.venv/bin/python scripts/simulate_traffic.py
```

1. **Feature phone** at `/simulator?lang=en`. Press Call, then 3, 1, then choose a place, then 1.
   Say that this is a simulator on the real menu, with no operator connected.
2. **SMS**, on the same page. Send `IMVURA`.
3. **Leaf check** at `/photo`. Upload the leaf, then the non-leaf photo.
4. **API** at `/api/docs`. Open `POST /api/v1/advice`, choose Try it out, and ask about bean rust.
   Then ask for a pesticide dose, and show it handed to a person.
5. **Dashboard** at `/dashboard`. Hover over the map, and point out the withheld forecast.
6. **Monitoring** at `/ops`, on slide 22. Refresh until the drift alert appears.

If something fails, use the screenshots in [demo-backup/](demo-backup/) and keep going.

## Likely questions

**Why no LLM?** Today's answers are quoted from approved text, so nothing unvetted reaches a
farmer. An LLM could rephrase those passages later, behind the same checks.

**How accurate is it in Burundi?** Unknown. It was tested on Ugandan photos, and collecting a local
test set is part of the ask.

**Is the Kirundi correct?** It is an unreviewed machine draft. Please help fix it.

**Why not Kinyarwanda speech models?** That is the concept note's plan, and it is not built yet.

**Why 119 communes?** No open geometry for the 42 new communes was found.

**Is it El Niño this year?** NOAA's index is strongly positive, but I do not forecast it. For
official outlooks, use IGEBU and ICPAC.
