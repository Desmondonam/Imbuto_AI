# 3. Installable PWA before a native Android app

**Decision.** Ship a PWA for smartphones. Inference runs on the server; photos taken offline queue
in the browser and upload when signal returns.

**Why.** One codebase reaches Android, iPhone and desktop, with no app-store download on a metered
connection. Feature-phone users are served by USSD, SMS and voice either way.

**Consequence.** Diagnosis needs signal eventually, which falls short of the note's on-device goal.
The exported ONNX model is the stepping stone to on-device inference, which is the next milestone.
