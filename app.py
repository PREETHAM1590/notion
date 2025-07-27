"""
A minimal Notion‑style web app for Windows built with FastAPI.

The goal of this sample is to provide a lightweight demonstration of some of
Notion’s core concepts – nested pages, rich text notes, simple task lists,
lightweight databases and an AI chat assistant – without re‑implementing
Notion’s entire feature set. Users can create pages, nest them hierarchically,
edit the contents of each page, create basic checklists and simple tables,
search through their workspace and chat with a placeholder AI.  Data is
persisted to a JSON file on disk so that sessions survive server restarts.

This app uses only libraries that are available in this environment.  It runs
as a web service on localhost using FastAPI and Jinja2 for templating.  To try
it out you can execute `uvicorn app:app --reload` from the `notion_clone`
directory and navigate to http://127.0.0.1:8000/ in your browser.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Request
import os
import requests
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "pages.json"
SETTINGS_FILE = BASE_DIR / "settings.json"

app = FastAPI(title="Notion‑style Workspace")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


#############################
# Data management utilities #
#############################

def load_data() -> Dict[str, dict]:
    """Load pages data from disk.  If the file does not exist the app starts with
    a single root page titled "Home".  Data is stored as a dictionary keyed by
    page ID.  Each page entry contains the title, raw content, children IDs,
    and an optional database (list of dictionaries)."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            # If the file is corrupted start fresh.
            pass
    # Initialize with a single root page if no data is present.
    root_id = str(uuid.uuid4())
    data = {
        root_id: {
            "title": "Home",
            "content": "Welcome to your Notion‑style workspace!",
            "children": [],
            "database": [],
        }
    }
    save_data(data)
    return data


def save_data(data: Dict[str, dict]) -> None:
    """Persist the pages dictionary to disk in JSON format."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


DATA = load_data()


def add_page(title: str, parent_id: Optional[str] = None) -> str:
    """Create a new page with the given title.  When parent_id is provided the
    new page is appended to the parent’s children list.  Returns the new
    page’s ID."""
    page_id = str(uuid.uuid4())
    DATA[page_id] = {
        "title": title.strip() or "Untitled",
        "content": "",
        "children": [],
        "database": [],
    }
    if parent_id and parent_id in DATA:
        DATA[parent_id]["children"].append(page_id)
    save_data(DATA)
    return page_id


def update_page(page_id: str, title: str, content: str) -> None:
    """Update the title and content of a page."""
    if page_id in DATA:
        DATA[page_id]["title"] = title.strip() or "Untitled"
        DATA[page_id]["content"] = content
        save_data(DATA)


def delete_page(page_id: str) -> None:
    """Delete a page and all of its children recursively."""
    if page_id not in DATA:
        return
    # Recursively delete children first
    for child_id in list(DATA[page_id]["children"]):
        delete_page(child_id)
    # Remove from parent’s children list
    for pid, pdata in DATA.items():
        if page_id in pdata.get("children", []):
            pdata["children"].remove(page_id)
    # Delete the page
    DATA.pop(page_id, None)
    save_data(DATA)


def get_page_tree() -> List[dict]:
    """Return a list representing the top‑level pages.  Each entry contains
    page_id, title and its children recursively.  This is used to render the
    sidebar."""
    def build_node(pid: str) -> dict:
        node = {"id": pid, "title": DATA[pid]["title"], "children": []}
        for cid in DATA[pid]["children"]:
            node["children"].append(build_node(cid))
        return node

    # Roots are pages that aren’t children of any other page.
    all_children = {cid for p in DATA.values() for cid in p.get("children", [])}
    root_ids = [pid for pid in DATA if pid not in all_children]
    return [build_node(pid) for pid in root_ids]


def search_pages(query: str) -> List[dict]:
    """Return a list of pages whose title or content contains the query string
    (case‑insensitive)."""
    results = []
    q = query.lower()
    for pid, pdata in DATA.items():
        if q in pdata["title"].lower() or q in pdata["content"].lower():
            results.append({"id": pid, "title": pdata["title"]})
    return results


#################################
# Utility functions for display #
#################################

def render_content(raw: str) -> str:
    """Render raw page content into simple HTML.  This function implements
    minimal markup: newlines become paragraphs, markdown‑like checklist syntax
    becomes checkboxes, and code blocks fenced with triple backticks are
    displayed monospaced.  For simplicity, other markdown features are ignored.
    """
    html_parts: List[str] = []
    in_code = False
    for line in raw.split("\n"):
        # Toggle code block
        if line.strip().startswith("```"):
            in_code = not in_code
            if in_code:
                html_parts.append("<pre><code>")
            else:
                html_parts.append("</code></pre>")
            continue
        if in_code:
            html_parts.append(html_escape(line) + "\n")
            continue
        # Checklists
        unchecked = re.match(r"^- \[ \] (.*)", line)
        checked = re.match(r"^- \[x\] (.*)", line, re.IGNORECASE)
        if unchecked:
            task = unchecked.group(1)
            html_parts.append(
                f'<label><input type="checkbox" disabled> {html_escape(task)}</label><br>'
            )
        elif checked:
            task = checked.group(1)
            html_parts.append(
                f'<label><input type="checkbox" checked disabled> {html_escape(task)}</label><br>'
            )
        else:
            # Simple paragraph with line breaks
            html_parts.append(f"<p>{html_escape(line)}</p>")
    return "\n".join(html_parts)


def html_escape(text: str) -> str:
    """Escape HTML special characters for safe rendering."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


###################
# Route handlers #
###################

@app.get("/")
async def home(request: Request):
    """Render the home page, displaying the page tree and a welcome message."""
    page_tree = get_page_tree()
    user = get_current_user(request)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "page_tree": page_tree,
            "user": user,
            "theme": SELECTED_THEME,
        },
    )


@app.get("/search")
async def search(request: Request, q: str = ""):
    """Search for pages containing the query string."""
    results = search_pages(q) if q else []
    page_tree = get_page_tree()
    user = get_current_user(request)
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "page_tree": page_tree,
            "query": q,
            "results": results,
            "user": user,
            "theme": SELECTED_THEME,
        },
    )


@app.get("/page/new")
async def new_page_form(request: Request, parent: Optional[str] = None):
    """Display a form for creating a new page (login required)."""
    # Require login
    if (resp := require_login(request)):
        return resp
    page_tree = get_page_tree()
    user = get_current_user(request)
    return templates.TemplateResponse(
        "new_page.html",
        {
            "request": request,
            "page_tree": page_tree,
            "parent": parent,
            "user": user,
            "theme": SELECTED_THEME,
        },
    )


@app.post("/page/new")
async def create_page(request: Request):
    """Handle form submission for creating a page.

    Because `python-multipart` is not available in this environment, we parse
    URL‑encoded form bodies manually using `urllib.parse.parse_qs`.  The
    expected fields are `title` and an optional `parent`.
    """
    import urllib.parse

    # Require login
    if (resp := require_login(request)):
        return resp
    body = await request.body()
    form = urllib.parse.parse_qs(body.decode())
    title = form.get("title", ["Untitled"])[0]
    parent = form.get("parent", [None])[0]
    new_id = add_page(title, parent)
    return RedirectResponse(url=f"/page/{new_id}", status_code=302)


@app.get("/page/{page_id}")
async def view_page(request: Request, page_id: str):
    if page_id not in DATA:
        return RedirectResponse(url="/", status_code=302)
    page = DATA[page_id]
    rendered = render_content(page.get("content", ""))
    page_tree = get_page_tree()
    user = get_current_user(request)
    return templates.TemplateResponse(
        "page.html",
        {
            "request": request,
            "page_tree": page_tree,
            "page_id": page_id,
            "page": page,
            "rendered": rendered,
            "user": user,
            "theme": SELECTED_THEME,
        },
    )


@app.get("/page/{page_id}/edit")
async def edit_page_form(request: Request, page_id: str):
    # Require login
    if (resp := require_login(request)):
        return resp
    if page_id not in DATA:
        return RedirectResponse(url="/", status_code=302)
    page_tree = get_page_tree()
    user = get_current_user(request)
    return templates.TemplateResponse(
        "edit_page.html",
        {
            "request": request,
            "page_tree": page_tree,
            "page_id": page_id,
            "page": DATA[page_id],
            "user": user,
            "theme": SELECTED_THEME,
        },
    )


@app.post("/page/{page_id}/edit")
async def edit_page(request: Request, page_id: str):
    """Update the title and content of a page (login required).  Form data is
    parsed manually because python‑multipart is unavailable."""
    # Require login
    if (resp := require_login(request)):
        return resp
    import urllib.parse

    body = await request.body()
    form = urllib.parse.parse_qs(body.decode())
    title = form.get("title", ["Untitled"])[0]
    content = form.get("content", [""])[0]
    update_page(page_id, title, content)
    return RedirectResponse(url=f"/page/{page_id}", status_code=302)


@app.get("/page/{page_id}/delete")
async def delete_page_route(request: Request, page_id: str):
    """Delete a page and its children (login required)."""
    if (resp := require_login(request)):
        return resp
    delete_page(page_id)
    return RedirectResponse(url="/", status_code=302)


#######################################
# Settings                            #
#######################################


@app.get("/settings")
async def settings_page(request: Request):
    """Display the settings page where users can choose a default AI model (login required)."""
    # Require login
    if (resp := require_login(request)):
        return resp
    page_tree = get_page_tree()
    user = get_current_user(request)
    available_models = ["Gemini", "GPT-4", "Claude", "Other"]
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "page_tree": page_tree,
            "selected_model": SELECTED_MODEL,
            "available_models": available_models,
            "user": user,
            "theme": SELECTED_THEME,
        },
    )


@app.post("/settings")
async def update_settings(request: Request):
    """Update settings based on form submission (login required).  Only the
    default AI model is currently configurable."""
    # Require login
    if (resp := require_login(request)):
        return resp
    import urllib.parse
    body = await request.body()
    form = urllib.parse.parse_qs(body.decode())
    model = form.get("model", [None])[0]
    global SELECTED_MODEL, SETTINGS
    if model:
        SELECTED_MODEL = model
        SETTINGS["model"] = model
        save_settings(SETTINGS)
    return RedirectResponse(url="/settings", status_code=302)


#######################################
# Simple database (table) operations  #
#######################################

@app.get("/page/{page_id}/database")
async def view_database(request: Request, page_id: str):
    # Require login
    if (resp := require_login(request)):
        return resp
    if page_id not in DATA:
        return RedirectResponse(url="/", status_code=302)
    page = DATA[page_id]
    database = page.get("database", [])
    page_tree = get_page_tree()
    user = get_current_user(request)
    return templates.TemplateResponse(
        "database.html",
        {
            "request": request,
            "page_tree": page_tree,
            "page_id": page_id,
            "page": page,
            "database": database,
            "user": user,
            "theme": SELECTED_THEME,
        },
    )


@app.post("/page/{page_id}/database/add")
async def add_db_row(request: Request, page_id: str):
    """Add a row to the page’s database.

    Without python‑multipart we parse form data manually.  The form may
    include existing column names as keys and values, plus `new_col` and
    `new_val` for defining a new column.  Empty values are ignored.
    """
    # Require login
    if (resp := require_login(request)):
        return resp
    import urllib.parse

    if page_id not in DATA:
        return RedirectResponse(url="/", status_code=302)
    body = await request.body()
    form = urllib.parse.parse_qs(body.decode())
    new_col = form.get("new_col", [""])[0].strip()
    new_val = form.get("new_val", [""])[0].strip()
    # Build row from existing fields; ignore blank values and the special fields.
    row: Dict[str, str] = {}
    for key, values in form.items():
        if key in ("new_col", "new_val"):
            continue
        value = values[0].strip()
        if value:
            row[key] = value
    if new_col:
        row[new_col] = new_val
    DATA[page_id].setdefault("database", []).append(row)
    save_data(DATA)
    return RedirectResponse(url=f"/page/{page_id}/database", status_code=302)


#######################################
# Authentication routes               #
#######################################


@app.get("/signup")
async def signup_form(request: Request):
    """Render the sign‑up page."""
    page_tree = get_page_tree()
    user = get_current_user(request)
    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "page_tree": page_tree,
            "user": user,
            "error": None,
            "theme": SELECTED_THEME,
        },
    )


@app.post("/signup")
async def signup_submit(request: Request):
    """Process sign‑up form submission.  Creates a new user via Supabase."""
    import urllib.parse
    body = await request.body()
    form = urllib.parse.parse_qs(body.decode())
    email = form.get("email", [""])[0]
    password = form.get("password", [""])[0]
    confirm = form.get("confirm", [""])[0]
    page_tree = get_page_tree()
    user = get_current_user(request)
    error: Optional[str] = None
    # Simple validation
    if not email or not password:
        error = "Email and password are required."
    elif password != confirm:
        error = "Passwords do not match."
    if error is None:
        success, err = supabase_signup(email, password)
        if success:
            # Redirect to login with a success query param
            return RedirectResponse(url="/login?signup=success", status_code=302)
        else:
            error = err or "Sign up failed."
    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "page_tree": page_tree,
            "user": user,
            "error": error,
            "theme": SELECTED_THEME,
        },
    )


@app.get("/login")
async def login_form(request: Request, signup: Optional[str] = None, next: str = "/"):
    """Render the login page.  If `signup=success` is present, display a
    congratulatory message."""
    page_tree = get_page_tree()
    user = get_current_user(request)
    message = None
    if signup == "success":
        message = "Account created successfully. Please log in."
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "page_tree": page_tree,
            "user": user,
            "message": message,
            "error": None,
            "next": next,
            "theme": SELECTED_THEME,
        },
    )


@app.post("/login")
async def login_submit(request: Request):
    """Process login form submission.  Authenticates against Supabase and
    creates a session."""
    import urllib.parse
    body = await request.body()
    form = urllib.parse.parse_qs(body.decode())
    email = form.get("email", [""])[0]
    password = form.get("password", [""])[0]
    next_path = form.get("next", ["/"])[0] or "/"
    page_tree = get_page_tree()
    success, data, err = supabase_login(email, password)
    if success and data:
        # Create session
        session_id = str(uuid.uuid4())
        SESSIONS[session_id] = {
            "email": email,
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
        }
        response = RedirectResponse(url=next_path, status_code=302)
        response.set_cookie("session_id", session_id, httponly=True)
        return response
    error = err or "Invalid credentials."
    user = get_current_user(request)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "page_tree": page_tree,
            "user": user,
            "message": None,
            "error": error,
            "next": next_path,
            "theme": SELECTED_THEME,
        },
    )


@app.get("/logout")
async def logout(request: Request):
    """Log the current user out by clearing their session."""
    session_id = request.cookies.get("session_id")
    if session_id and session_id in SESSIONS:
        SESSIONS.pop(session_id, None)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_id")
    return response


#######################################
# AI chat assistant (placeholder)     #
#######################################

# In a production environment you would integrate with external models here.  The
# stub below simply echoes the user’s prompt and indicates which model was
# selected.  If you wish to plug in a real model, extend this function to call
# the appropriate API using your own keys and handle the response.
def call_ai_model(model: Optional[str], prompt: str) -> str:
    """Simulate sending a prompt to an AI model.

    If `model` is None or an empty string, the default `SELECTED_MODEL` is used.
    This stub can be replaced with real API calls to services like Gemini or
    OpenAI.
    """
    chosen = model or SELECTED_MODEL
    return f"[Model: {chosen}] You said: {prompt}"


CHAT_HISTORY: List[Dict[str, str]] = []

# Load settings at startup.  Settings include the default AI model.
def load_settings() -> Dict[str, str]:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    # Default settings if file missing or corrupted
    return {"model": "Gemini", "theme": "light"}


def save_settings(settings: Dict[str, str]) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


SETTINGS = load_settings()
SELECTED_MODEL = SETTINGS.get("model", "Gemini")
SELECTED_THEME = SETTINGS.get("theme", "light")

# Load Supabase configuration from environment variables.  Users should set
# SUPABASE_URL (the project REST URL, without trailing slash) and SUPABASE_KEY
# (the service API key) in their environment.  If these are not set, the
# application will still run but authentication will be disabled.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# In‑memory session store.  When a user logs in a session identifier is
# generated and stored here along with their Supabase tokens and email.  In a
# production environment you would use a more robust session backend.
SESSIONS: Dict[str, Dict[str, str]] = {}

# ---------------------------------------------------------------------------
# Supabase authentication helpers
# ---------------------------------------------------------------------------

def supabase_signup(email: str, password: str) -> tuple[bool, Optional[str]]:
    """Attempt to sign up a new user in Supabase.  Returns (success, error).

    On success the user must confirm their email if the Supabase project
    requires it.  On failure the error message is returned.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False, "Supabase URL or key not configured."
    url = f"{SUPABASE_URL}/auth/v1/signup"
    headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    payload = {"email": email, "password": password}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code >= 400:
            return False, resp.text
        return True, None
    except Exception as exc:
        return False, str(exc)


def supabase_login(email: str, password: str) -> tuple[bool, Optional[dict], Optional[str]]:
    """Authenticate a user with Supabase using the password grant.

    Returns (success, data, error).  On success data contains the token
    information; on failure error contains the error message.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False, None, "Supabase URL or key not configured."
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    payload = {"email": email, "password": password}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code >= 400:
            return False, None, resp.text
        return True, resp.json(), None
    except Exception as exc:
        return False, None, str(exc)


def get_current_user(request: Request) -> Optional[dict]:
    """Retrieve the current logged‑in user from the session cookie."""
    session_id = request.cookies.get("session_id")
    if session_id and session_id in SESSIONS:
        return SESSIONS[session_id]
    return None


def get_current_theme() -> str:
    """Return the currently selected UI theme ("light" or "dark")."""
    global SELECTED_THEME
    return SELECTED_THEME


def require_login(request: Request):
    """If the user is not logged in, redirect to the login page with a `next`
    parameter pointing back to the current path.  If logged in, return None.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
    return None


@app.get("/ai")
async def ai_chat(request: Request):
    # Require login
    if (resp := require_login(request)):
        return resp
    page_tree = get_page_tree()
    user = get_current_user(request)
    return templates.TemplateResponse(
        "ai.html",
        {
            "request": request,
            "page_tree": page_tree,
            "history": CHAT_HISTORY,
            "selected_model": SELECTED_MODEL,
            "user": user,
            "theme": SELECTED_THEME,
        },
    )


@app.post("/ai")
async def ai_chat_post(request: Request):
    """Handle AI chat submissions (login required).  Parse form data manually."""
    # Require login
    if (resp := require_login(request)):
        return resp
    import urllib.parse

    body = await request.body()
    form = urllib.parse.parse_qs(body.decode())
    model = form.get("model", [""])[0]
    message = form.get("message", [""])[0]
    response_text = call_ai_model(model, message)
    CHAT_HISTORY.append({"role": "user", "text": message})
    CHAT_HISTORY.append({"role": "assistant", "text": response_text})
    return RedirectResponse(url="/ai", status_code=302)


#################################
# Theme toggling                #
#################################

@app.post("/toggle_theme")
async def toggle_theme(request: Request):
    """Toggle between light and dark themes.

    The current theme is stored in the SETTINGS dict and persisted to the
    settings file.  When toggled, the user is redirected back to the
    referring page or home.
    """
    global SELECTED_THEME, SETTINGS
    # Flip the theme
    SELECTED_THEME = "dark" if SELECTED_THEME == "light" else "light"
    SETTINGS["theme"] = SELECTED_THEME
    save_settings(SETTINGS)
    # Redirect back to the page the user came from or to home
    referer = request.headers.get("referer") or "/"
    return RedirectResponse(url=referer, status_code=302)


###############################
# Entry point for development #
###############################

# When running this module directly via `python app.py`, automatically start
# the FastAPI server using Uvicorn.  This allows the user to run the app
# without explicitly invoking uvicorn from the command line.
if __name__ == "__main__":
    import uvicorn

    # Bind to all interfaces on port 8000.  In a production deployment you
    # should use a proper ASGI server and configuration.  The reload flag is
    # omitted here to keep things simple for local use.
    uvicorn.run(app, host="127.0.0.1", port=8000)
