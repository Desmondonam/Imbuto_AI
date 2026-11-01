# 2. HTML-first web app instead of React

**Decision.** The farmer app is server-rendered HTML that works with JavaScript off. JavaScript
and a service worker only enhance it.

**Why.** On 2G, a framework bundle costs more than the whole page budget of 14 KB, and a blank
screen until scripts load is the failure mode we most need to avoid. Older phones also fail
quietly on modern bundles.

**Consequence.** Rich dashboard interaction is limited. If ministries need it, a React dashboard
can use the same JSON API without touching the farmer app.
