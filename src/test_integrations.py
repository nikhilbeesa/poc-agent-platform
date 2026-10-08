"""Jira / Azure DevOps push, against local mock servers (no real tenant needed)."""
import base64, json, os, re, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, ".")
os.environ["INTEGRATIONS_ALLOW_LOCAL"] = "1"
from test_clarifications import _project
from orchestrator import run_full_pipeline
from integrations import sync, backlog
from integrations.http import IntegrationError, validate_url


class Mock:
    """A tiny fake tool server. kind='jira' or 'ado'; behaviour flags simulate real-world project differences."""
    def __init__(self, kind, **flags):
        self.kind, self.flags, self.calls, self.n = kind, flags, [], 0
        outer = self
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _go(self, method):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                data = json.loads(body) if body else None
                auth = self.headers.get("Authorization", "")
                outer.calls.append((method, self.path, data, self.headers.get("Content-Type", ""), auth))
                code, resp = outer.handle(method, self.path, data, auth)
                payload = json.dumps(resp).encode() if resp is not None else b""
                self.send_response(code); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
            do_GET = lambda s: s._go("GET"); do_POST = lambda s: s._go("POST")
            do_PUT = lambda s: s._go("PUT"); do_PATCH = lambda s: s._go("PATCH")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self): self.srv.shutdown()

    def handle(self, m, path, data, auth):
        if self.flags.get("bad_auth") and "secret-token" not in base64.b64decode(auth.split()[-1] + "==").decode(errors="ignore"):
            return 401, {"message": "no"}
        return (self._jira if self.kind == "jira" else self._ado)(m, path, data)

    def _jira(self, m, path, data):
        if path.endswith("/myself"): return 200, {"displayName": "Test User"}
        if path.endswith("/project/APP"):
            return 200, {"name": "App", "issueTypes": [{"name": n} for n in ("Epic", "Story", "Task")]}
        if path.endswith("/issueLink"): return 201, None
        if m == "PUT": return 204, None
        if m == "POST" and path.endswith("/issue"):
            f = data["fields"]
            if self.flags.get("no_priority") and "priority" in f:
                return 400, {"errors": {"priority": "Field 'priority' cannot be set. It is not on the appropriate screen."}}
            if self.flags.get("epic_name") and f["issuetype"]["name"] == "Epic" and "customfield_10011" not in f:
                return 400, {"errors": {"customfield_10011": "Epic Name is required."}}
            self.n += 1
            return 201, {"id": str(self.n), "key": f"APP-{self.n}"}
        return 404, {"errorMessages": ["not found"]}

    def _ado(self, m, path, data):
        if "/_apis/projects/" in path: return 200, {"name": "Proj"}
        types = ["Epic", "Feature", "Issue"] if self.flags.get("basic") else ["Epic", "Feature", "User Story", "Task"]
        if "/workitemtypes" in path: return 200, {"value": [{"name": t} for t in types]}
        if m == "POST" and "/workitems/$" in path:
            if self.flags.get("no_priority") and any(o["path"].endswith("Priority") for o in data):
                return 400, {"message": "TF401326: Field 'Microsoft.VSTS.Common.Priority' cannot be found."}
            self.n += 1
            return 200, {"id": self.n, "url": f"{self.url}/_apis/wit/workItems/{self.n}",
                         "_links": {"html": {"href": f"{self.url}/Proj/_workitems/edit/{self.n}"}}}
        if m == "PATCH": return 200, {"id": 1}
        return 404, {"message": "nope"}


def _backlog_project():
    ctx = _project(skip_every=9); run_full_pipeline(ctx); return ctx

JIRA = lambda mk, **k: {"base_url": mk.url, "email": "me@x.com", "token": "secret-token", "project": "APP"}
ADO = lambda mk: {"base_url": mk.url + "/myorg", "token": "secret-token", "project": "Proj"}


def test_jira_push_links_and_idempotent():
    ctx = _backlog_project(); bk = backlog.build_backlog(ctx); mk = Mock("jira", bad_auth=True)
    try:
        r = sync.push(ctx, "jira", JIRA(mk), {})
        assert r["created"] == len(bk["epics"]) + len(bk["stories"]) and not r["failed"], r["failed"][:2]
        posts = [c for c in mk.calls if c[0] == "POST" and c[1].endswith("/issue")]
        story_posts = [c for c in posts if c[2]["fields"]["issuetype"]["name"] == "Story"]
        assert all(c[2]["fields"]["parent"]["key"].startswith("APP-") for c in story_posts)      # attached to its epic
        f = story_posts[0][2]["fields"]
        assert f["description"]["type"] == "doc" and f["summary"].startswith("US-") and f["priority"]["name"] in ("High", "Medium", "Low")
        assert " " not in "".join(f["labels"]) and "ai-generated" in f["labels"]
        assert r["dependency_links"] == sum(len(s["dependencies"]) for s in bk["stories"]) > 0
        n_calls = len(mk.calls)
        r2 = sync.push(ctx, "jira", JIRA(mk), {})                                               # push again: nothing new
        assert r2["created"] == 0 and r2["unchanged"] == r["created"] and r2["dependency_links"] == 0
        assert len([c for c in mk.calls[n_calls:] if c[0] == "POST"]) == 0
        key = next(iter(ctx.integration_links)); assert "secret-token" not in json.dumps(ctx.integration_links)
        # content changed upstream -> only updated when asked
        ctx.integration_links[key]["US-001"]["hash"] = "old"
        assert sync.push(ctx, "jira", JIRA(mk), {})["updated"] == 0
        assert sync.push(ctx, "jira", JIRA(mk), {"update_existing": True})["updated"] == 1
    finally: mk.stop()


def test_jira_adapts_to_project_differences():
    ctx = _backlog_project(); mk = Mock("jira", no_priority=True, epic_name=True)
    try:
        r = sync.push(ctx, "jira", JIRA(mk), {})
        assert not r["failed"] and any("priority" in w for w in r["warnings"])                  # priority dropped, story still created
        epics = [c for c in mk.calls if c[0] == "POST" and c[1].endswith("/issue") and c[2]["fields"]["issuetype"]["name"] == "Epic"]
        assert any("customfield_10011" in c[2]["fields"] for c in epics)                        # old-style 'Epic Name' supplied
    finally: mk.stop()


def test_ado_agile_and_basic():
    ctx = _backlog_project(); bk = backlog.build_backlog(ctx); mk = Mock("ado")
    try:
        r = sync.push(ctx, "ado", ADO(mk), {})
        assert not r["failed"] and r["created"] == len(bk["epics"]) + len(bk["stories"]), r["failed"][:2]
        posts = [c for c in mk.calls if c[0] == "POST" and "/workitems/$" in c[1]]
        assert all(c[3] == "application/json-patch+json" for c in posts)
        story = next(c for c in posts if "$User%20Story" in c[1] or "$User Story" in c[1])
        paths = {o["path"] for o in story[2]}
        assert "/fields/Microsoft.VSTS.Common.AcceptanceCriteria" in paths and "/relations/-" in paths   # AC field + epic parent
        assert any(c[0] == "PATCH" and "Dependency-Reverse" in json.dumps(c[2]) for c in mk.calls)
        assert base64.b64decode(story[4].split()[-1]).decode() == ":secret-token"                      # PAT as Basic, empty user
    finally: mk.stop()
    ctx2 = _backlog_project(); mk2 = Mock("ado", basic=True, no_priority=True)
    try:
        r = sync.push(ctx2, "ado", ADO(mk2), {})
        assert not r["failed"] and any("Priority" in w for w in r["warnings"])
        st = next(c for c in mk2.calls if c[0] == "POST" and "$Issue" in c[1])
        desc = next(o["value"] for o in st[2] if o["path"].endswith("System.Description"))
        assert "Acceptance criteria" in desc                                                     # no AC field in Basic -> inside description
    finally: mk2.stop()


def test_safety():
    os.environ.pop("INTEGRATIONS_ALLOW_LOCAL")           # production behaviour: localhost / private addresses are refused
    try:
        _safety()
    finally:
        os.environ["INTEGRATIONS_ALLOW_LOCAL"] = "1"


def _safety():
    for bad in ("http://example.atlassian.net", "https://evil.example.com", "https://169.254.169.254", "https://localhost:8080", ""):
        try: validate_url(bad, (".atlassian.net",), "X"); assert False, bad
        except IntegrationError: pass
    os.environ["INTEGRATIONS_ALLOW_LOCAL"] = "1"         # the mock server is local
    mk = Mock("jira", bad_auth=True)
    try:
        try: sync.check("jira", {**JIRA(mk), "token": "wrong-token-123"}); assert False
        except IntegrationError as e: assert e.status == 401 and "wrong-token-123" not in str(e)
    finally: mk.stop()
    ctx = _project(skip_every=9)                       # no stories generated yet
    try: sync.push(ctx, "jira", {"base_url": "x"}, {}); assert False
    except IntegrationError: pass


def test_server_endpoints_end_to_end():
    import time
    sys.path.insert(0, "../webapp")
    os.environ["JIRA_API_TOKEN"] = "secret-token"             # server-side default: the form may leave the token blank
    import server
    ctx = _backlog_project(); server.PROJECTS["pt"] = ctx; c = server.app.test_client(); mk = Mock("jira", bad_auth=True)
    try:
        assert c.get("/api/integrations/config").get_json()["jira"]["token_configured"] is True
        assert "secret-token" not in json.dumps(c.get("/api/integrations/config").get_json())
        body = {"creds": {"base_url": mk.url, "email": "me@x.com", "project": "APP"}}
        assert c.post("/api/project/pt/integrations/jira/check", json=body).get_json()["story_type"] == "Story"
        started = c.post("/api/project/pt/integrations/jira/push", json=body).get_json()
        assert "push_id" in started and "job_id" not in started        # 'job_id' would be hijacked by the UI's agent-job poller
        for _ in range(150):
            st = c.get(f"/api/project/pt/integrations/push/{started['push_id']}").get_json()
            if st["status"] != "running": break
            time.sleep(0.2)
        assert st["status"] == "done" and not st["result"]["failed"] and "secret-token" not in json.dumps(st)
        assert c.get("/api/project/other/integrations/push/x").status_code in (404, 200)
        bad = c.post("/api/project/pt/integrations/jira/check", json={"creds": {"base_url": "https://evil.example.com", "email": "a", "token": "b", "project": "APP"}})
        assert bad.status_code == 400 and "not an allowed host" in bad.get_json()["error"]
        rec = server._record_from_ctx(ctx)                              # links survive a save/reload; credentials never stored
        assert rec["feasibility"]["integrations"] and "secret-token" not in json.dumps(rec, default=str)
        assert server._ctx_from_record(rec).integration_links == ctx.integration_links
    finally: mk.stop()


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("PASS ", n)
