import asyncio
import os
import time
from functools import partial
from typing import List

import altair as alt
import arel
import numpy as np
import pandas as pd
from databases import Database
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseSettings

from ..core import Portfolio, SketchPad
from . import auth, data, models

# ## PLAN FOR DIRECTORY STRUCTURE?

# main.py (very short, just create app method, that registers everything)
# pages.py, or is all the "browse-paths"
# components.py or is a bunch of {api}/name
# api.py or is the actual api
# data.py or is the actual database creation, and raw object models
# aut.py the auth stuff
# settings.py the settings for the app


# NOTE: The client API (parent sketch library), will reference in code, the component API,
#  in order to embed capability in jupyter notebooks or streamlit apps (figure out how to embed)
# the component into the client.
# client library, can make HTML blocks, with appropriate "wrapping" (div context wrapper, some sizing stuff, basic composition)
#  -> and then render those or embed them into the client [[ Important to render with a streamlit example for demo purposes ]]
# https://docs.streamlit.io/library/components/create
# Rendering Python objects having methods that output HTML, such as IPython __repr_html__.

# components have a 'rapid render' mode (use another request lifecycle to get data) or a "synchronous" -> oh,
# async or sync mode.. Async mode includes client code in JS for query of data later.
# offline / online mode could be useful, to give things like "always on" or "self-updating" ones.


# https://fastapi.tiangolo.com/advanced/settings/
class Settings(BaseSettings):
    app_name: str = "SketchAPI"
    db_url: str = "sqlite+aiosqlite:///test.db"
    debug: bool = False


dir_path = os.path.dirname(os.path.realpath(__file__))

settings = Settings()
app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(dir_path, "templates"))
database = Database(settings.db_url)

# from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
# app.add_middleware(HTTPSRedirectMiddleware)

externalApiApp = FastAPI(root_path="/api")

externalApiApp.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/api", externalApiApp)
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(dir_path, "static")),
    name="static",
)


@app.on_event("startup")
async def database_connect():
    await database.connect()
    await data.setup_database(database)


@app.on_event("shutdown")
async def database_disconnect():
    await database.disconnect()


# Set up data (for now just storing stuff on app...)
app.portfolio = Portfolio()

if _debug := settings.debug:
    hot_reload = arel.HotReload(paths=[arel.Path(dir_path)])
    app.add_websocket_route("/hot-reload", route=hot_reload, name="hot-reload")
    app.add_event_handler("startup", hot_reload.startup)
    app.add_event_handler("shutdown", hot_reload.shutdown)
    templates.env.globals["DEBUG"] = _debug
    templates.env.globals["hot_reload"] = hot_reload
    print(("=" * 30 + "\n") * 2 + " " * 12 + "DEBUG\n" + ("=" * 30 + "\n") * 2)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


@app.get("/login")
async def login(request: Request, redirect_uri: str = "/"):
    return templates.TemplateResponse(
        "login.html", {"request": request, "redirect_uri": redirect_uri}
    )


@app.get("/logout")
async def logout(redirectResponse=Depends(auth.logout)):
    return redirectResponse


# Any 401 sends to login page
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse(
            app.url_path_for(name="login")
            + ("" if request.url.path == "/" else f"?redirect_uri={request.url.path}")
        )
    elif exc.status_code == 404:
        return templates.TemplateResponse("page/404.html", {"request": request})
    raise exc


@app.get("/404")
async def not_found(request: Request):
    return templates.TemplateResponse("page/404.html", {"request": request})


@app.get("/references")
async def references(
    request: Request, user: auth.User = Depends(auth.get_browser_user)
):
    pf = await data.get_portfolio(database, user.username)
    return templates.TemplateResponse(
        "page/references.html",
        {
            "request": request,
            "user": user,
            "portfolio": pf,
        },
    )


@app.get("/search")
async def search(
    request: Request, user: auth.User = Depends(auth.get_browser_user), q: str = ""
):
    # obviously no need to normally get the whole thing... but for now, we'll do it.
    if q:
        pf = await data.get_portfolio(database, user.username)
        to_keep = [
            x for x in pf.sketchpads.values() if q in x.reference.to_searchable_string()
        ]
        pf = Portfolio(sketchpads=to_keep)
    else:
        pf = Portfolio()

    return templates.TemplateResponse(
        "page/search.html",
        {
            "request": request,
            "user": user,
            "portfolio": pf,
            "q": q,
        },
    )


@app.get("/apple")
async def apple(request: Request, user: auth.User = Depends(auth.get_browser_user)):
    return "🍎"


@app.get("/")
async def root(request: Request, user: auth.User = Depends(auth.get_browser_user)):
    pf = await data.get_portfolio(database, user.username)
    return templates.TemplateResponse(
        "page/root.html",
        {
            "request": request,
            "sketchcount": len(pf.sketchpads),
            "user": user,
        },
    )


@app.post("/token")
async def login_for_access_token(
    token_response=Depends(auth.login_for_access_token),
):
    return token_response


@app.get("/cardinality_histogram")
async def cardhisto(request: Request, user: auth.User = Depends(auth.get_browser_user)):
    pf = await data.get_portfolio(database, user.username)

    cards = np.array(
        [
            x.get_sketchdata_by_name("HyperLogLog").count()
            for x in pf.sketchpads.values()
        ]
    )
    # hist, bins = np.histogram(cards)
    upper = pow(2, np.ceil(np.log(np.max(cards) / np.log(2))))
    bins = np.geomspace(1, upper, num=100)
    hist, *_ = np.histogram(cards, bins=bins)
    # should be geometric mean...
    df = pd.DataFrame({"x": bins[:-1], "x1": bins[1:], "y": hist})
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(
                "x", title="Unique Count", scale=alt.Scale(type="log", domainMin=1)
            ),
            # x2="x2",
            # y=alt.Y("y", title="Number", scale=alt.Scale(type="log")),
            y=alt.Y("y", title="Count"),
        )
        .properties(width="container", height=300)
    )
    return chart.to_dict()


@externalApiApp.post("/upload_sketchpad")
# The request to send a sketchpad to our services
async def upload_sketchpad(
    sketchpad: models.SketchPad, user: auth.User = Depends(auth.get_token_user)
):
    # Ensure sketchpad parses correctly
    print(sketchpad)
    SketchPad.from_dict(sketchpad.dict())
    # add the pydantic sketchpad directly to database
    await data.add_sketchpad(database, user.username, sketchpad)
    return {"status": "ok"}


@externalApiApp.post("/upload_portfolio")
async def upload_portfolio(
    sketchpads: List[models.SketchPad], user: auth.User = Depends(auth.get_token_user)
):
    # Ensure sketchpad parses correctly
    for sketchpad in sketchpads:
        SketchPad.from_dict(sketchpad.dict())
    # add the pydantic sketchpad directly to database
    add_sketchpad = partial(data.add_sketchpad, database, user.username)
    await asyncio.gather(*map(add_sketchpad, sketchpads))
    return {"status": "ok"}


@externalApiApp.get("/get_approx_best_joins")
async def get_approx_best_joins(
    sketchpad_ids: List[str], user: auth.User = Depends(auth.get_token_user)
):
    pf = await data.get_portfolio(database, user.username)
    pf = pf.get_approx_pk_sketchpads()
    myspads = [
        x
        async for x in data.get_sketchpads_by_id(database, sketchpad_ids, user.username)
    ]
    possibilities = []
    for sketch in myspads:
        high_overlaps = pf.closest_overlap(sketch)
        for score, sketchpad in high_overlaps:
            possibilities.append(
                {
                    "score": score,
                    "left_sketchpad": sketch.to_dict(),
                    "right_sketchpad": sketchpad.to_dict(),
                }
            )
    return sorted(possibilities, key=lambda x: x["score"], reverse=True)[:5]


@externalApiApp.get("/component/get_approx_best_joins")
async def get_approx_best_joins(
    request: Request, best_joins=Depends(get_approx_best_joins)
):
    pf = Portfolio(
        sketchpads=[SketchPad.from_dict(x["right_sketchpad"]) for x in best_joins]
    )
    return templates.TemplateResponse(
        "component/references.html",
        {"request": request, "portfolio": pf},
    )
