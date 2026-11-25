"""Authenticated loopback API and local dashboard over the product commands."""

import argparse
import hmac
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.templating import Jinja2Templates

from .application import Coordinator
from .domain import Conflict, Invalid, NotFound, Principal, require
from .store import Store
from .web_security import COOKIE, UNSAFE, LocalBoundary, Sessions

ASSETS = Path(__file__).with_name("web_assets")
TEMPLATES = Path(__file__).with_name("web_templates")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: StrictStr = Field(min_length=1, max_length=200)


class ProjectInput(Input):
    spec: dict


class ReviseInput(ProjectInput):
    expected_version: StrictInt


class DiscoveryInput(Input):
    expected_version: StrictInt
    question: StrictStr = Field(min_length=1, max_length=8192)
    answer: StrictStr = Field(min_length=1, max_length=8192)
    requirements: list | None = None


class VersionInput(Input):
    expected_version: StrictInt


class ReasonInput(VersionInput):
    reason: StrictStr = Field(min_length=1, max_length=8192)


class PlanInput(Input):
    milestone_key: StrictStr
    spec: dict
    expected_project_version: StrictInt


class GsdImportInput(Input):
    milestone_key: StrictStr = Field(min_length=1, max_length=80)
    snapshot: StrictStr = Field(min_length=1, max_length=4096)
    digest: StrictStr = Field(min_length=64, max_length=64)
    plans: StrictStr = Field(min_length=1, max_length=4096)
    expected_project_version: StrictInt
    baseline_revision: StrictStr = Field(min_length=40, max_length=64)
    max_attempts: StrictInt
    check_timeout_seconds: StrictInt


class ApprovalInput(Input):
    digest: StrictStr
    expected_project_version: StrictInt
    expected_milestone_version: StrictInt


class ClaimInput(Input):
    milestone_key: StrictStr
    task_key: StrictStr
    expected_project_version: StrictInt
    expected_milestone_version: StrictInt


class ResultInput(Input):
    outcome: StrictStr
    detail: StrictStr = ""


class ModelPolicyInput(Input):
    milestone_key: StrictStr
    spec: dict
    expected_project_version: StrictInt
    expected_milestone_version: StrictInt


class ModelAssignInput(Input):
    role: StrictStr
    route_id: StrictStr
    requested: dict
    expected_attempt_version: StrictInt
    expected_project_version: StrictInt


class ModelPermitInput(Input):
    route_id: StrictStr
    submission_id: StrictStr
    reserved_units: StrictInt
    request_digest: StrictStr
    expected_project_version: StrictInt


class ModelUsageInput(Input):
    usage: dict
    expected_version: StrictInt


class HeadAuthorizationInput(Input):
    previous_head: StrictStr
    new_head: StrictStr
    authority_generation: StrictInt
    repository: StrictStr
    artifacts: StrictStr


class ExactSpecInput(Input):
    spec: dict
    digest: StrictStr
    expected_version: StrictInt
    repository: StrictStr
    artifacts: StrictStr


class PromotionInput(Input):
    expected_version: StrictInt
    repository: StrictStr
    artifacts: StrictStr


class ReconcileInput(Input):
    repository: StrictStr
    artifacts: StrictStr


def init_token(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(secrets.token_urlsafe(32) + "\n")
    return path


def read_token(path):
    path = Path(path)
    require(
        not path.is_symlink() and not path.is_junction(),
        "access token must be a regular private file",
    )
    info = path.stat()
    require(info.st_nlink == 1 and info.st_size <= 256, "invalid access token file")
    if os.name != "nt":
        require(info.st_mode & 0o077 == 0, "access token file must be private")
    token = path.read_text(encoding="utf-8").strip()
    require(32 <= len(token) <= 128, "invalid local access token")
    return token


def create_app(database, token_file, *, origin="http://127.0.0.1:8765", sessions=None):
    parsed = urlparse(origin)
    require(
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port is not None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password,
        "use a canonical loopback origin with an explicit port",
    )
    auth = sessions or Sessions(read_token(token_file))
    templates = Jinja2Templates(directory=str(TEMPLATES))

    @asynccontextmanager
    async def lifespan(app):
        with Store(database) as store:
            app.state.coordinator = Coordinator(store, Principal("local-web-developer"))
            yield

    app = FastAPI(
        title="Orchestrator local workspace",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.sessions = auth
    app.add_middleware(LocalBoundary, host=parsed.netloc, origin=origin)
    app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")

    def actor(request: Request):
        row = auth.lookup(request.cookies.get(COOKIE))
        if row is None:
            raise HTTPException(401, "Sign in to the local workspace")
        request.state.session = row
        if request.method in UNSAFE:
            csrf = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(csrf.encode(), row.csrf.encode()):
                raise HTTPException(
                    403, "Refresh the workspace and retry with its CSRF token"
                )
        return request.app.state.coordinator

    authenticated_core = Depends(actor)

    @app.exception_handler(Invalid)
    async def domain_error(_request, error):
        status = (
            409
            if isinstance(error, Conflict)
            else 404
            if isinstance(error, NotFound)
            else 422
        )
        return JSONResponse(
            {"error": type(error).__name__, "message": str(error)}, status_code=status
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _error):
        return JSONResponse(
            {"error": "Invalid", "message": "Request fields are invalid"},
            status_code=422,
        )

    @app.exception_handler(sqlite3.Error)
    async def database_error(_request, _error):
        return JSONResponse(
            {
                "error": "StoreUnavailable",
                "message": "The store is unavailable; inspect state before retrying the same command",
            },
            status_code=503,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {"error": "HTTPError", "message": str(error.detail)},
                status_code=error.status_code,
            )
        return templates.TemplateResponse(
            request=request,
            name="info.html",
            context={
                "title": "Page not found",
                "message": "This page is not available. Return to your local workspace.",
            },
            status_code=error.status_code,
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(
            request=request, name="workspace.html", context={}
        )

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="info.html",
            context={
                "title": "Local privacy",
                "message": "Project data and audit history stay in your configured local store. This version makes no model calls. The browser uses one essential session cookie. Access tokens and sessions are not project data and must stay private.",
            },
        )

    @app.get("/terms", response_class=HTMLResponse)
    def terms(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="info.html",
            context={
                "title": "Workspace usage",
                "message": "This is a local development preview. Plan approval records your exact intent. Scripted outcomes do not prove implementation or independent acceptance. Review evidence before enabling future execution or publishing a release.",
            },
        )

    @app.post("/api/session")
    async def login(request: Request):
        body = await request.json()
        if set(body) != {"token"}:
            raise HTTPException(422, "Provide only the local access token")
        result = auth.login(body["token"])
        if result is None:
            raise HTTPException(401, "Access token was not accepted")
        old = request.cookies.get(COOKIE)
        if old:
            auth.logout(old)
        key, row = result
        response = JSONResponse({"csrf": row.csrf, "expires_in": auth.ttl})
        response.set_cookie(
            COOKIE,
            key,
            max_age=auth.ttl,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return response

    @app.get("/api/session")
    def current_session(request: Request, _app=authenticated_core):
        return {"csrf": request.state.session.csrf, "actor": "local-web-developer"}

    @app.post("/api/logout")
    def logout(request: Request, _app=authenticated_core):
        auth.logout(request.cookies.get(COOKIE))
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
        return response

    @app.get("/api/projects")
    def projects(core=authenticated_core):
        return {"projects": core.list_projects()}

    @app.post("/api/projects")
    def project_create(body: ProjectInput, core=authenticated_core):
        return core.create_project(body.spec, command_id=body.command_id)

    @app.get("/api/projects/{project_id}")
    def project_status(project_id: str, core=authenticated_core):
        return core.status(project_id)

    @app.put("/api/projects/{project_id}")
    def project_revise(project_id: str, body: ReviseInput, core=authenticated_core):
        return core.revise_project(
            project_id,
            body.spec,
            expected_version=body.expected_version,
            command_id=body.command_id,
        )

    @app.post("/api/projects/{project_id}/discovery")
    def discovery_record(
        project_id: str, body: DiscoveryInput, core=authenticated_core
    ):
        return core.record_discovery(
            project_id,
            expected_version=body.expected_version,
            question=body.question,
            answer=body.answer,
            requirements=body.requirements,
            command_id=body.command_id,
        )

    @app.post("/api/projects/{project_id}/plans")
    def plan_submit(project_id: str, body: PlanInput, core=authenticated_core):
        return core.submit_plan(
            project_id,
            body.milestone_key,
            body.spec,
            expected_project_version=body.expected_project_version,
            command_id=body.command_id,
        )

    @app.post("/api/projects/{project_id}/plan-import-gsd")
    def plan_import_gsd(project_id: str, body: GsdImportInput, core=authenticated_core):
        return core.import_gsd(
            project_id,
            body.milestone_key,
            body.snapshot,
            body.digest,
            body.plans,
            expected_project_version=body.expected_project_version,
            baseline_revision=body.baseline_revision,
            max_attempts=body.max_attempts,
            check_timeout_seconds=body.check_timeout_seconds,
            command_id=body.command_id,
        )

    @app.post("/api/plans/{plan_id}/approve")
    def plan_approve(plan_id: str, body: ApprovalInput, core=authenticated_core):
        return core.approve_plan(
            plan_id,
            body.digest,
            expected_project_version=body.expected_project_version,
            expected_milestone_version=body.expected_milestone_version,
            command_id=body.command_id,
        )

    @app.post("/api/projects/{project_id}/pause")
    def pause(project_id: str, body: ReasonInput, core=authenticated_core):
        return core.pause(
            project_id,
            expected_version=body.expected_version,
            reason=body.reason,
            command_id=body.command_id,
        )

    @app.post("/api/projects/{project_id}/recover")
    def recover(project_id: str, body: ReasonInput, core=authenticated_core):
        return core.recover(
            project_id,
            expected_version=body.expected_version,
            reason=body.reason,
            command_id=body.command_id,
        )

    @app.post("/api/projects/{project_id}/resume")
    def resume(project_id: str, body: VersionInput, core=authenticated_core):
        return core.resume(
            project_id,
            expected_version=body.expected_version,
            command_id=body.command_id,
        )

    @app.post("/api/projects/{project_id}/claims")
    def claim(project_id: str, body: ClaimInput, core=authenticated_core):
        return core.claim_task(
            project_id,
            body.milestone_key,
            body.task_key,
            expected_project_version=body.expected_project_version,
            expected_milestone_version=body.expected_milestone_version,
            command_id=body.command_id,
        )

    @app.post("/api/attempts/{attempt_id}/scripted-start")
    def scripted_start(attempt_id: str, body: VersionInput, core=authenticated_core):
        return core.start_scripted(
            attempt_id,
            expected_version=body.expected_version,
            command_id=body.command_id,
        )

    @app.post("/api/operations/{operation_id}/scripted-result")
    def scripted_result(operation_id: str, body: ResultInput, core=authenticated_core):
        return core.record_scripted_result(
            operation_id, body.outcome, detail=body.detail, command_id=body.command_id
        )

    @app.post("/api/attempts/{attempt_id}/scripted-abandon")
    def scripted_abandon(attempt_id: str, body: ReasonInput, core=authenticated_core):
        return core.abandon_scripted(
            attempt_id,
            expected_version=body.expected_version,
            reason=body.reason,
            command_id=body.command_id,
        )

    @app.get("/api/events")
    def events(after: int = 0, limit: int = 100, core=authenticated_core):
        return core.event_page(after=after, limit=limit)

    @app.get("/api/projects/{project_id}/milestones/{milestone_key}/cost")
    def cost_report(project_id: str, milestone_key: str, core=authenticated_core):
        return core.cost_report(project_id, milestone_key)

    @app.post("/api/projects/{project_id}/model-policy")
    def model_policy(project_id: str, body: ModelPolicyInput, core=authenticated_core):
        return core.approve_model_policy(
            project_id,
            body.milestone_key,
            body.spec,
            expected_project_version=body.expected_project_version,
            expected_milestone_version=body.expected_milestone_version,
            command_id=body.command_id,
        )

    @app.post("/api/attempts/{attempt_id}/model-assignment")
    def model_assignment(
        attempt_id: str, body: ModelAssignInput, core=authenticated_core
    ):
        return core.assign_model(
            attempt_id,
            body.role,
            body.route_id,
            body.requested,
            expected_attempt_version=body.expected_attempt_version,
            expected_project_version=body.expected_project_version,
            command_id=body.command_id,
        )

    @app.post("/api/model-assignments/{assignment_id}/permit")
    def model_permit(
        assignment_id: str, body: ModelPermitInput, core=authenticated_core
    ):
        return core.begin_model_permit(
            assignment_id,
            body.route_id,
            body.submission_id,
            body.reserved_units,
            body.request_digest,
            expected_project_version=body.expected_project_version,
            command_id=body.command_id,
        )

    @app.post("/api/model-permits/{permit_id}/lose-response")
    def model_lose_response(
        permit_id: str, body: VersionInput, core=authenticated_core
    ):
        return core.lose_model_response(
            permit_id,
            expected_version=body.expected_version,
            command_id=body.command_id,
        )

    @app.post("/api/model-permits/{permit_id}/usage")
    def model_usage(permit_id: str, body: ModelUsageInput, core=authenticated_core):
        return core.observe_model_usage(
            permit_id,
            body.usage,
            expected_version=body.expected_version,
            command_id=body.command_id,
        )

    @app.post("/api/attempts/{attempt_id}/diverged-head")
    def diverged_head(
        attempt_id: str, body: HeadAuthorizationInput, core=authenticated_core
    ):
        return core.authorize_diverged_head(
            attempt_id,
            body.previous_head,
            body.new_head,
            body.authority_generation,
            repository=body.repository,
            artifacts=body.artifacts,
            command_id=body.command_id,
        )

    @app.post("/api/integration-proposals/{proposal_id}/regressions")
    def approve_regressions(
        proposal_id: str, body: ExactSpecInput, core=authenticated_core
    ):
        return core.approve_regressions(
            proposal_id,
            body.spec,
            body.digest,
            expected_version=body.expected_version,
            repository=body.repository,
            artifacts=body.artifacts,
            command_id=body.command_id,
        )

    @app.post("/api/integration-proposals/{proposal_id}/evidence")
    def approve_evidence(
        proposal_id: str, body: ExactSpecInput, core=authenticated_core
    ):
        return core.approve_evidence(
            proposal_id,
            body.spec,
            body.digest,
            expected_version=body.expected_version,
            repository=body.repository,
            artifacts=body.artifacts,
            command_id=body.command_id,
        )

    @app.post("/api/integration-proposals/{proposal_id}/promotion")
    def begin_promotion(
        proposal_id: str, body: PromotionInput, core=authenticated_core
    ):
        return core.begin_promotion(
            proposal_id,
            expected_version=body.expected_version,
            repository=body.repository,
            artifacts=body.artifacts,
            command_id=body.command_id,
        )

    @app.post("/api/integration-proposals/{proposal_id}/promote")
    def promote(proposal_id: str, body: PromotionInput, core=authenticated_core):
        return core.promote(
            proposal_id,
            expected_version=body.expected_version,
            repository=body.repository,
            artifacts=body.artifacts,
        )

    @app.post("/api/integration-proposals/{proposal_id}/promotion-reconcile")
    def reconcile_promotion(
        proposal_id: str, body: ReconcileInput, core=authenticated_core
    ):
        return core.reconcile_promotion(
            proposal_id, repository=body.repository, artifacts=body.artifacts
        )

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Local authenticated planning workspace; live execution remains disabled"
    )
    parser.add_argument(
        "--db", type=Path, default=Path(".local/orchestrator/state.sqlite")
    )
    parser.add_argument(
        "--token-file", type=Path, default=Path(".local/orchestrator/web-token")
    )
    parser.add_argument("--init-token", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if args.init_token:
        print(f"Created private access token file: {init_token(args.token_file)}")
        return 0
    require(1 <= args.port <= 65535, "invalid loopback port")
    import uvicorn

    app = create_app(args.db, args.token_file, origin=f"http://127.0.0.1:{args.port}")
    uvicorn.run(
        app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
