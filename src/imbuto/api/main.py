"""HTTP layer: JSON API, web pages and gateway webhooks. Logic stays in the core."""

import hmac
import time
from collections import defaultdict, deque
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from imbuto import __version__
from imbuto.channels import sms
from imbuto.channels.menu import Menu, as_ussd
from imbuto.channels.voice import as_voice_xml
from imbuto.core.service import CROPS, LANGUAGES, Imbuto, t
from imbuto.monitoring import metrics

HERE = Path(__file__).parent
MAX_UPLOAD = 2_000_000
Image.MAX_IMAGE_PIXELS = 40_000_000  # refuses decompression bombs
RATE_LIMIT = (30, 60)  # requests, seconds
STATUS_COLOURS = {"very_dry": "#8c510a", "dry": "#d8b365", "normal": "#e8e8e8",
                  "wet": "#67a9cf", "very_wet": "#2166ac"}  # fmt: skip

templates = Jinja2Templates(directory=HERE / "templates")


class AdviceRequest(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    lang: str = Field(default="rn", pattern="^(rn|fr|en)$")


class FeedbackRequest(BaseModel):
    prediction_id: int
    correct: bool


def create_app(app_core: Imbuto | None = None) -> FastAPI:
    core = app_core or Imbuto()
    app = FastAPI(title="Imbuto AI", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)  # fmt: skip
    app.add_middleware(GZipMiddleware, minimum_size=300, compresslevel=9)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    hits: dict[str, deque] = defaultdict(deque)

    def limited(request: Request) -> None:
        """Small in-process limit, so one client cannot starve a shared CPU."""
        limit, window = RATE_LIMIT
        client = request.client.host if request.client else "unknown"
        now, recent = time.monotonic(), hits[client]
        while recent and now - recent[0] > window:
            recent.popleft()
        if len(recent) >= limit:
            raise HTTPException(429, "Too many requests")
        recent.append(now)

    def _token_ok(request: Request, expected: str) -> bool:
        supplied = request.headers.get("x-token") or request.query_params.get("token", "")
        return not expected or hmac.compare_digest(supplied, expected)

    def gateway(request: Request) -> None:
        if not _token_ok(request, core.settings.gateway_token):
            raise HTTPException(401, "Bad gateway token")

    def operator(request: Request) -> None:
        if not _token_ok(request, core.settings.ops_token):
            raise HTTPException(401, "Bad operator token")

    def demo_only() -> None:
        """The simulator has no caller identity, so it could register anyone's number."""
        if core.settings.env == "production":
            raise HTTPException(404, "Not found")

    def lang_of(request: Request) -> str:
        lang = request.query_params.get("lang") or request.cookies.get("lang", "rn")
        return lang if lang in LANGUAGES else "rn"

    def page(request: Request, name: str, **context) -> HTMLResponse:
        lang = lang_of(request)
        commune_id = request.cookies.get("commune")
        context |= {"lang": lang, "tr": lambda key, **v: t(lang, key, **v),
                    "commune": core.commune_by_id.get(commune_id or ""),
                    "demo": core.settings.demo_content}  # fmt: skip
        response = templates.TemplateResponse(request, name, context)
        if "lang" in request.query_params and lang == request.query_params["lang"]:
            response.set_cookie("lang", lang, max_age=31536000, samesite="lax")
        return response

    def read_image(data: bytes) -> bytes:
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Image too large")
        return data

    def run_diagnosis(data: bytes, lang: str, channel: str):
        try:
            return core.diagnose(read_image(data), lang, channel)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise HTTPException(422, "Could not read this image") from error

    # Health
    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        return {"status": "ready", "version": __version__,
                "models": {"crop_health": core.crop_model.version,
                           "rain_data_through": core.rain_status["observed_through"]}}  # fmt: skip

    # JSON API
    @app.get("/api/v1/communes", tags=["reference"])
    def api_communes():
        return [{k: c[k] for k in ("id", "name", "province", "district")} for c in core.communes]

    @app.get("/api/v1/rain/{commune_id}", tags=["answers"])
    def api_rain(commune_id: str, lang: str = "en"):
        result = core.rain_for(commune_id, lang)
        if result is None:
            raise HTTPException(404, "Unknown commune")
        result.pop("experimental_shortfall_probability")
        return result

    @app.get("/api/v1/prices/{crop}", tags=["answers"])
    def api_price(crop: str, commune_id: str | None = None, lang: str = "en"):
        if crop not in CROPS:
            raise HTTPException(404, "Unknown crop")
        return core.price_for(crop, commune_id, lang)

    @app.post("/api/v1/advice", tags=["answers"], dependencies=[Depends(limited)])
    def api_advice(body: AdviceRequest):
        answer = core.ask(body.question, body.lang, "api")
        return {"answer": answer.text, "source": answer.source_id, "score": answer.score,
                "escalated": answer.escalate}  # fmt: skip

    @app.post("/api/v1/diagnose", tags=["models"], dependencies=[Depends(limited)])
    def api_diagnose(image: UploadFile = File(), lang: str = Form("en")):
        result = run_diagnosis(image.file.read(), lang, "api")
        return {"prediction_id": result.id, "message": result.message,
                "model_version": core.crop_model.version, **vars(result.diagnosis)}  # fmt: skip

    @app.post("/api/v1/feedback", tags=["models"])
    def api_feedback(body: FeedbackRequest):
        core.store.log_feedback(body.prediction_id, body.correct)
        return {"status": "recorded"}

    @app.get("/api/v1/models", tags=["models"])
    def api_models():
        crop = {k: v for k, v in core.crop_model.card.items() if k != "metrics"}
        metrics_ = {k: v for k, v in core.crop_model.card["metrics"].items()
                    if k not in ("reference_confidence", "per_class")}  # fmt: skip
        return {"crop_health": {**crop, "metrics": metrics_}, "rain": core.rain_bundle["card"]}

    # Gateways
    @app.post("/gateway/ussd", response_class=PlainTextResponse,
              dependencies=[Depends(gateway)], tags=["gateways"])  # fmt: skip
    def ussd(sessionId: str = Form(), phoneNumber: str = Form(), text: str = Form("")):
        metrics.REQUESTS.labels("ussd").inc()
        digit = text.split("*")[-1] if text else None
        return as_ussd(Menu(core, "ussd").handle(sessionId, phoneNumber, digit))

    @app.post("/gateway/sms", response_class=PlainTextResponse,
              dependencies=[Depends(gateway)], tags=["gateways"])  # fmt: skip
    def sms_in(sender: str = Form(alias="from"), text: str = Form("")):
        metrics.REQUESTS.labels("sms").inc()
        body = sms.reply(core, sender, text)
        core.store.queue_sms(sender, body)
        return body

    @app.post("/gateway/voice", dependencies=[Depends(gateway)], tags=["gateways"])
    def voice(
        request: Request,
        sessionId: str = Form(),
        callerNumber: str = Form(),
        dtmfDigits: str | None = Form(None),
    ):
        metrics.REQUESTS.labels("voice").inc()
        screen = Menu(core, "voice").handle(sessionId, callerNumber, dtmfDigits)
        lang = core.store.load_session(sessionId).get("lang", "rn")
        xml = as_voice_xml(screen, lang, str(request.url))
        return Response(xml, media_type="application/xml")

    # Web pages
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(request: Request):
        lang = lang_of(request)
        commune_id = request.cookies.get("commune")
        rain = core.rain_for(commune_id, lang) if commune_id else None
        return page(request, "home.html", rain=rain)

    @app.get("/area", response_class=HTMLResponse, include_in_schema=False)
    def area(request: Request):
        return page(request, "area.html", communes=core.communes)

    @app.post("/area", include_in_schema=False)
    def area_save(commune_id: str = Form()):
        response = Response(status_code=303, headers={"location": "/"})
        if commune_id in core.commune_by_id:
            response.set_cookie("commune", commune_id, max_age=31536000, samesite="lax")
        return response

    @app.get("/prices", response_class=HTMLResponse, include_in_schema=False)
    def prices(request: Request):
        lang, commune_id = lang_of(request), request.cookies.get("commune")
        return page(request, "prices.html",
                    prices=[core.price_for(c, commune_id, lang) for c in CROPS])  # fmt: skip

    @app.get("/ask", response_class=HTMLResponse, include_in_schema=False)
    def ask_form(request: Request):
        return page(request, "ask.html", answer=None, question="")

    @app.post("/ask", response_class=HTMLResponse, include_in_schema=False,
              dependencies=[Depends(limited)])  # fmt: skip
    def ask_post(request: Request, question: str = Form(max_length=300)):
        answer = core.ask(question, lang_of(request), "web")
        return page(request, "ask.html", answer=answer, question=question)

    @app.get("/photo", response_class=HTMLResponse, include_in_schema=False)
    def photo_form(request: Request):
        return page(request, "photo.html", result=None, done=False)

    @app.post("/photo", response_class=HTMLResponse, include_in_schema=False,
              dependencies=[Depends(limited)])  # fmt: skip
    def photo_post(request: Request, image: UploadFile = File()):
        result = run_diagnosis(image.file.read(), lang_of(request), "web")
        return page(request, "photo.html", result=result, done=False)

    @app.post("/photo/feedback", response_class=HTMLResponse, include_in_schema=False)
    def photo_feedback(request: Request, prediction_id: int = Form(), correct: int = Form()):
        core.store.log_feedback(prediction_id, bool(correct))
        return page(request, "photo.html", result=None, done=True)

    @app.get("/offline", response_class=HTMLResponse, include_in_schema=False)
    def offline(request: Request):
        return page(request, "offline.html")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return Response((HERE / "static" / "sw.js").read_bytes(), media_type="text/javascript",
                        headers={"cache-control": "no-cache"})  # fmt: skip

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    def dashboard(request: Request):
        rows = []
        for commune in core.communes:
            status = core.rain_by_id[commune["id"]]
            rows.append({**commune, **status, "colour": STATUS_COLOURS[status["status"]]})
        summary = []
        for province in core.provinces():
            part = [r for r in rows if r["province"] == province]
            percents = sorted(r["percent_of_normal"] for r in part)
            dry = sum(r["status"] in ("dry", "very_dry") for r in part)
            summary.append({"province": province, "communes": len(part),
                            "median": percents[len(percents) // 2], "dry": dry})  # fmt: skip
        return page(request, "dashboard.html", rows=rows, summary=summary,
                    status=core.rain_status, colours=STATUS_COLOURS, reports=reports_by_kind(),
                    gate=core.rain_bundle["card"]["promotion_gate"])  # fmt: skip

    def reports_by_kind() -> dict:
        with core.store.db() as con:
            found = con.execute("select kind, count(*) n from reports group by kind").fetchall()
        return {r["kind"]: r["n"] for r in found}

    @app.get("/simulator", response_class=HTMLResponse, include_in_schema=False,
             dependencies=[Depends(demo_only)])  # fmt: skip
    def simulator(request: Request):
        return page(request, "simulator.html", session=uuid4().hex)

    @app.post("/simulator/ussd", response_class=JSONResponse, include_in_schema=False,
              dependencies=[Depends(demo_only)])  # fmt: skip
    def simulator_ussd(session: str = Form(), phone: str = Form(), digit: str = Form("")):
        screen = Menu(core, "ussd").handle(session, phone, digit or None)
        return {"text": screen.text, "end": screen.end}

    @app.post("/simulator/sms", response_class=JSONResponse, include_in_schema=False,
              dependencies=[Depends(demo_only)])  # fmt: skip
    def simulator_sms(phone: str = Form(), text: str = Form()):
        return {"reply": sms.reply(core, phone, text)}

    @app.get("/ops", response_class=HTMLResponse, include_in_schema=False,
             dependencies=[Depends(operator)])  # fmt: skip
    def ops(request: Request):
        return page(request, "ops.html", ops=core.ops_summary(), card=core.crop_model.card,
                    gate=core.rain_bundle["card"]["promotion_gate"])  # fmt: skip

    @app.get("/metrics", include_in_schema=False, dependencies=[Depends(operator)])
    def prometheus():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def app() -> FastAPI:
    return create_app()
