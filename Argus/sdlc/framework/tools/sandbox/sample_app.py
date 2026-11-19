"""The sandbox's sample app, ETL repo and knowledge base, written so the KB generators can read them.

The app (`acme-claims/`) has the folder layout the generators in `tools/kbgen/` scan: API routers in
`api/apps/<app>/api.py`, the front end in `web/src/app/**/page.tsx` and `web/src/Services/*.ts`, and the
ETL repo `claims-etl/` beside it with `scripts/sql/*.sql` and `scripts/python/*.py`. The app also runs:
`run.py` starts the Django API and the Next.js front end over a copy of the sandbox's `sample.db`. The KB folder gets
the hand-kept files a team writes itself (table and entity registries, semantic layer, lineage, routing
map, curated impact chains, domain context); `build_kb` then runs the generators in the installed repo,
so the endpoint, component and ETL registries, the cross-layer matrix, the ontology and the link graph
come from the sample code. Everything is made up.
"""
import os
import subprocess
import sys
import tempfile

import yaml

DB, SCHEMA = "ACME_CLAIMS_DB", "CLAIMS"

COLUMNS = {
    "SDLC_MEMBER": [("MEMBER_ID", "INTEGER PRIMARY KEY"), ("FIRST_NM", "TEXT"), ("LAST_NM", "TEXT"),
                    ("BIRTH_YR", "INTEGER"), ("PLAN_CD", "TEXT"), ("STATE_CD", "TEXT")],
    "SDLC_PROVIDER": [("PROVIDER_ID", "INTEGER PRIMARY KEY"), ("PROVIDER_NM", "TEXT"), ("SPECIALTY_CD", "TEXT"),
                      ("STATE_CD", "TEXT")],
    "SDLC_CONTRACT": [("CONTRACT_ID", "INTEGER PRIMARY KEY"), ("PROVIDER_ID", "INTEGER REFERENCES SDLC_PROVIDER"),
                      ("START_DT", "TEXT"), ("END_DT", "TEXT"), ("RATE_PCT", "REAL"), ("STATUS_CD", "TEXT")],
    "SDLC_CLAIM": [("CLAIM_ID", "INTEGER PRIMARY KEY"), ("MEMBER_ID", "INTEGER REFERENCES SDLC_MEMBER"),
                   ("PROVIDER_ID", "INTEGER REFERENCES SDLC_PROVIDER"),
                   ("CONTRACT_ID", "INTEGER REFERENCES SDLC_CONTRACT"), ("SERVICE_DT", "TEXT"),
                   ("STATUS_CD", "TEXT"), ("LOB_CD", "TEXT")],
    "SDLC_CLAIM_LINE": [("LINE_ID", "INTEGER PRIMARY KEY"), ("CLAIM_ID", "INTEGER REFERENCES SDLC_CLAIM"),
                        ("PROC_CD", "TEXT"), ("BILLED_AMT", "REAL"), ("ALLOWED_AMT", "REAL")],
    "SDLC_PAYMENT": [("PAYMENT_ID", "INTEGER PRIMARY KEY"), ("CLAIM_ID", "INTEGER REFERENCES SDLC_CLAIM"),
                     ("PAID_DT", "TEXT"), ("PAID_AMT", "REAL")],
}
TABLES = {t: ", ".join("%s %s" % c for c in cols) for t, cols in COLUMNS.items()}
STAGE_TABLES = {"SDLC_CLAIM_STAGE": "claims from the clearinghouse, loaded each night",
                "SDLC_PAYMENT_STAGE": "payments from the payment system, loaded each night"}
MODULE = {"SDLC_MEMBER": "claims", "SDLC_PROVIDER": "contracts", "SDLC_CONTRACT": "contracts",
          "SDLC_CLAIM": "claims", "SDLC_CLAIM_LINE": "claims", "SDLC_PAYMENT": "payments",
          "SDLC_CLAIM_STAGE": "claims", "SDLC_PAYMENT_STAGE": "payments"}

# ------------------------------------------------------------------------------------------ the app

API_ROOT = '''from ninja import NinjaAPI

from apps.claims.api import router as claims_router
from apps.contracts.api import router as contracts_router
from apps.payments.api import router as payments_router

api = NinjaAPI(title="Acme Claims API")

ROUTES = {
    "/claims/": claims_router,
    "/contracts/": contracts_router,
    "/payments/": payments_router,
}
for prefix, router in ROUTES.items():
    api.add_router(prefix, router)
'''

DB_MODULE = '''"""The app's database: SQLite at ACME_DB, or api/.data/acme.db (run.py copies the sandbox's sample.db there)."""
import os
import sqlite3

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def path():
    return os.environ.get("ACME_DB") or os.path.join(API_DIR, ".data", "acme.db")


def connect():
    if not os.path.exists(path()):
        raise RuntimeError("no database at %s: start the app with run.py, or set ACME_DB" % path())
    con = sqlite3.connect(path())
    con.row_factory = sqlite3.Row
    return con


def rows(sql, **params):
    con = connect()
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


def one(sql, **params):
    found = rows(sql, **params)
    return found[0] if found else None


def write(sql, **params):
    con = connect()
    try:
        with con:
            return con.execute(sql, params).lastrowid
    finally:
        con.close()
'''

CLAIMS_API = '''from ninja import Router
from ninja.errors import HttpError

from apps.claims import queries
from apps.claims.schema import ClaimIn, ClaimOut, TimelineStep

router = Router(tags=["claims"])


@router.get("/list", response=list[ClaimOut])
def list_claims(request, member_id: int, status: str = None):
    """The member's claims, newest first, with the provider name."""
    return queries.rows(queries.LIST_CLAIMS, member_id=member_id, status=status)


@router.post("/submit", response=ClaimOut)
def submit_claim(request, payload: ClaimIn):
    """Save a claim and its lines; a member without a plan is refused."""
    if not queries.one(queries.MEMBER_PLAN, member_id=payload.member_id):
        raise HttpError(400, "The member has no active plan")
    claim_id = queries.write(queries.INSERT_CLAIM, member_id=payload.member_id, provider_id=payload.provider_id,
                             contract_id=payload.contract_id, service_date=payload.service_date, lob=payload.lob)
    for line in payload.lines:
        queries.write(queries.INSERT_LINE, claim_id=claim_id, proc_code=line.proc_code, billed=line.billed)
    return queries.one(queries.ONE_CLAIM, claim_id=claim_id)


@router.get("/timeline", response=list[TimelineStep])
def claim_timeline(request, claim_id: int):
    """Each status the claim went through, with its date."""
    claim = queries.one(queries.TIMELINE, claim_id=claim_id)
    if not claim:
        raise HttpError(404, "No such claim")
    steps = [{"status": "submitted", "date": claim["service_date"]}]
    if claim["status"] != "pending":
        steps.append({"status": claim["status"], "date": claim["paid_date"] or claim["service_date"]})
    return steps
'''

CLAIMS_QUERIES = '''"""SQL of the claims app."""
from apps.db import one, rows, write  # noqa: F401

LIST_CLAIMS = """
SELECT c.CLAIM_ID AS claim_id, c.SERVICE_DT AS service_date, c.STATUS_CD AS status, c.LOB_CD AS lob,
       p.PROVIDER_NM AS provider_name
FROM SDLC_CLAIM c JOIN SDLC_PROVIDER p ON c.PROVIDER_ID = p.PROVIDER_ID
WHERE c.MEMBER_ID = :member_id AND (:status IS NULL OR c.STATUS_CD = :status)
ORDER BY c.SERVICE_DT DESC
"""

ONE_CLAIM = """
SELECT c.CLAIM_ID AS claim_id, c.SERVICE_DT AS service_date, c.STATUS_CD AS status, c.LOB_CD AS lob,
       p.PROVIDER_NM AS provider_name
FROM SDLC_CLAIM c JOIN SDLC_PROVIDER p ON c.PROVIDER_ID = p.PROVIDER_ID
WHERE c.CLAIM_ID = :claim_id
"""

MEMBER_PLAN = "SELECT PLAN_CD FROM SDLC_MEMBER WHERE MEMBER_ID = :member_id AND PLAN_CD IS NOT NULL"

INSERT_CLAIM = """
INSERT INTO SDLC_CLAIM (MEMBER_ID, PROVIDER_ID, CONTRACT_ID, SERVICE_DT, STATUS_CD, LOB_CD)
VALUES (:member_id, :provider_id, :contract_id, :service_date, 'pending', :lob)
"""

INSERT_LINE = "INSERT INTO SDLC_CLAIM_LINE (CLAIM_ID, PROC_CD, BILLED_AMT) VALUES (:claim_id, :proc_code, :billed)"

TIMELINE = """
SELECT c.STATUS_CD AS status, c.SERVICE_DT AS service_date, y.PAID_DT AS paid_date
FROM SDLC_CLAIM c LEFT JOIN SDLC_PAYMENT y ON y.CLAIM_ID = c.CLAIM_ID
WHERE c.CLAIM_ID = :claim_id
"""
'''

CLAIMS_SCHEMA = '''from ninja import Schema


class ClaimLineIn(Schema):
    proc_code: str
    billed: float


class ClaimIn(Schema):
    member_id: int
    provider_id: int
    contract_id: int
    service_date: str
    lob: str
    lines: list[ClaimLineIn]


class ClaimOut(Schema):
    claim_id: int
    service_date: str
    status: str
    lob: str
    provider_name: str = None


class TimelineStep(Schema):
    status: str
    date: str
'''

CONTRACTS_API = '''from ninja import Router
from ninja.errors import HttpError

from apps.contracts import queries
from apps.contracts.schema import ContractOut, RateIn

router = Router(tags=["contracts"])


def found(contract_id):
    contract = queries.one(queries.ONE_CONTRACT, contract_id=contract_id)
    if not contract:
        raise HttpError(404, "No such contract")
    return contract


@router.get("/list", response=list[ContractOut])
def list_contracts(request, provider_id: int = None):
    """Contracts with their provider, rate and status."""
    return queries.rows(queries.LIST_CONTRACTS, provider_id=provider_id)


@router.put("/rate", response=ContractOut)
def update_rate(request, contract_id: int, payload: RateIn):
    """Change the rate a contract pays."""
    found(contract_id)
    queries.write(queries.UPDATE_RATE, rate_pct=payload.rate_pct, contract_id=contract_id)
    return found(contract_id)


@router.post("/expire", response=ContractOut)
def expire_contract(request, contract_id: int):
    """End a contract today; its claims stop paying."""
    found(contract_id)
    queries.write(queries.EXPIRE, contract_id=contract_id)
    return found(contract_id)
'''

CONTRACTS_QUERIES = '''"""SQL of the contracts app."""
from apps.db import one, rows, write  # noqa: F401

LIST_CONTRACTS = """
SELECT k.CONTRACT_ID AS contract_id, k.START_DT AS start_date, k.END_DT AS end_date, k.RATE_PCT AS rate_pct,
       k.STATUS_CD AS status, p.PROVIDER_NM AS provider_name
FROM SDLC_CONTRACT k JOIN SDLC_PROVIDER p ON k.PROVIDER_ID = p.PROVIDER_ID
WHERE (:provider_id IS NULL OR k.PROVIDER_ID = :provider_id)
ORDER BY k.CONTRACT_ID
"""

ONE_CONTRACT = """
SELECT k.CONTRACT_ID AS contract_id, k.START_DT AS start_date, k.END_DT AS end_date, k.RATE_PCT AS rate_pct,
       k.STATUS_CD AS status, p.PROVIDER_NM AS provider_name
FROM SDLC_CONTRACT k JOIN SDLC_PROVIDER p ON k.PROVIDER_ID = p.PROVIDER_ID
WHERE k.CONTRACT_ID = :contract_id
"""

UPDATE_RATE = "UPDATE SDLC_CONTRACT SET RATE_PCT = :rate_pct WHERE CONTRACT_ID = :contract_id"

EXPIRE = "UPDATE SDLC_CONTRACT SET STATUS_CD = 'expired', END_DT = CURRENT_DATE WHERE CONTRACT_ID = :contract_id"
'''

CONTRACTS_SCHEMA = '''from ninja import Schema


class RateIn(Schema):
    rate_pct: float


class ContractOut(Schema):
    contract_id: int
    start_date: str
    end_date: str
    rate_pct: float
    status: str
    provider_name: str = None
'''

PAYMENTS_API = '''from ninja import Router

from apps.payments import queries
from apps.payments.schema import MonthTotal, PaymentLine

router = Router(tags=["payments"])


@router.get("/monthly", response=list[MonthTotal])
def monthly_payments(request, lob: str = None):
    """What was paid each month, by line of business."""
    return queries.rows(queries.MONTHLY, lob=lob)


@router.get("/lines", response=list[PaymentLine])
def payment_lines(request, payment_id: int):
    """The claim lines a payment paid."""
    return queries.rows(queries.LINES, payment_id=payment_id)
'''

PAYMENTS_QUERIES = '''"""SQL of the payments app."""
from apps.db import one, rows, write  # noqa: F401

MONTHLY = """
SELECT substr(y.PAID_DT, 1, 7) AS month, c.LOB_CD AS lob, ROUND(SUM(y.PAID_AMT), 2) AS total
FROM SDLC_PAYMENT y JOIN SDLC_CLAIM c ON y.CLAIM_ID = c.CLAIM_ID
WHERE (:lob IS NULL OR c.LOB_CD = :lob)
GROUP BY 1, 2
ORDER BY 1 DESC, 2
"""

LINES = """
SELECT l.LINE_ID AS line_id, l.PROC_CD AS proc_code, l.BILLED_AMT AS billed, l.ALLOWED_AMT AS allowed
FROM SDLC_PAYMENT y JOIN SDLC_CLAIM_LINE l ON l.CLAIM_ID = y.CLAIM_ID
WHERE y.PAYMENT_ID = :payment_id
"""
'''

PAYMENTS_SCHEMA = '''from ninja import Schema


class MonthTotal(Schema):
    month: str
    lob: str
    total: float


class PaymentLine(Schema):
    line_id: int
    proc_code: str
    billed: float
    allowed: float = None
'''

MANAGE_PY = '''#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "acme.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
'''

SETTINGS_PY = '''"""Settings of the Acme Claims API: a sample app for this machine only, never deployed."""
SECRET_KEY = "sample-app-local-only"
DEBUG = True
ALLOWED_HOSTS = ["*"]  # it binds to 127.0.0.1 only (run.py); previews and test clients send other hosts
INSTALLED_APPS = ["django.contrib.staticfiles", "ninja"]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "acme.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}]
DATABASES = {}
STATIC_URL = "/static/"
USE_TZ = True
'''

URLS_PY = '''from django.urls import path

from apps.app.api import api

urlpatterns = [path("acme/api/", api.urls)]
'''

REQUIREMENTS = "Django>=4.2,<6\ndjango-ninja>=1.1,<2\n"

ENDPOINTS_TS = '''const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
const bp = () => process.env.NEXT_PUBLIC_API_PATH || "/acme";

const CLAIMS_BASE = () => `${BASE_URL}${bp()}/api/claims`;
const CONTRACTS_BASE = () => `${BASE_URL}${bp()}/api/contracts`;
const PAYMENTS_BASE = () => `${BASE_URL}${bp()}/api/payments`;

export const ENDPOINTS = {
  listClaims: `${CLAIMS_BASE()}/list`,
  submitClaim: `${CLAIMS_BASE()}/submit`,
  claimTimeline: `${CLAIMS_BASE()}/timeline`,
  listContracts: `${CONTRACTS_BASE()}/list`,
  updateRate: `${CONTRACTS_BASE()}/rate`,
  expireContract: `${CONTRACTS_BASE()}/expire`,
  monthlyPayments: `${PAYMENTS_BASE()}/monthly`,
  paymentLines: `${PAYMENTS_BASE()}/lines`,
};

export const call = async (url: string, init?: RequestInit) => {
  const res = await fetch(url, { ...init, headers: { "Content-Type": "application/json" } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`);
  return body;
};
'''

CLAIMS_SERVICE = '''import { ENDPOINTS, call } from "./Utility/endpoints";

export const getClaims = (memberId: number, status?: string) =>
  call(`${ENDPOINTS.listClaims}?member_id=${memberId}${status ? `&status=${status}` : ""}`);

export const submitClaim = (claim: object) =>
  call(ENDPOINTS.submitClaim, { method: "POST", body: JSON.stringify(claim) });

export const getTimeline = (claimId: number) =>
  call(`${ENDPOINTS.claimTimeline}?claim_id=${claimId}`);
'''

CONTRACTS_SERVICE = '''import { ENDPOINTS, call } from "./Utility/endpoints";

export const getContracts = (providerId?: number) =>
  call(`${ENDPOINTS.listContracts}${providerId ? `?provider_id=${providerId}` : ""}`);

export const setRate = (contractId: number, ratePct: number) =>
  call(`${ENDPOINTS.updateRate}?contract_id=${contractId}`, { method: "PUT", body: JSON.stringify({ rate_pct: ratePct }) });

export const expire = (contractId: number) =>
  call(`${ENDPOINTS.expireContract}?contract_id=${contractId}`, { method: "POST" });
'''

PAYMENTS_SERVICE = '''import { ENDPOINTS, call } from "./Utility/endpoints";

export const getMonthly = (lob?: string) =>
  call(`${ENDPOINTS.monthlyPayments}${lob ? `?lob=${lob}` : ""}`);

export const getLines = (paymentId: number) =>
  call(`${ENDPOINTS.paymentLines}?payment_id=${paymentId}`);
'''

PAGES = {
    "claims": '''"use client";
import { useEffect, useState } from "react";
import { getClaims, getTimeline } from "@/Services/ClaimsService";
import StatusTimeline from "@/_components/StatusTimeline";

export default function MyClaims() {
  const [memberId, setMemberId] = useState(1);
  const [claims, setClaims] = useState<any[]>([]);
  const [timeline, setTimeline] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    getClaims(memberId).then((c) => { setClaims(c); setError(""); }, (e) => setError(e.message));
  }, [memberId]);
  return (
    <main>
      <h1>My claims</h1>
      <label>Member <input type="number" min={1} value={memberId} onChange={(e) => setMemberId(Number(e.target.value))} /></label>
      {error && <p role="alert">{error}</p>}
      <ul>{claims.map((c) => (
        <li key={c.claim_id} onClick={() => getTimeline(c.claim_id).then(setTimeline)} style={{ cursor: "pointer" }}>
          {c.service_date} {c.provider_name} {c.status}
        </li>))}
      </ul>
      <StatusTimeline steps={timeline} />
    </main>
  );
}
''',
    "claims/submit": '''"use client";
import { useState } from "react";
import { submitClaim } from "@/Services/ClaimsService";

const START = { member_id: 1, provider_id: 1, contract_id: 1, service_date: new Date().toISOString().slice(0, 10),
  lob: "Commercial", proc_code: "CPT99213", billed: 120 };

export default function SubmitClaim() {
  const [form, setForm] = useState<Record<string, string | number>>(START);
  const [message, setMessage] = useState("");
  const send = async () => {
    const { proc_code, billed, ...claim } = form;
    try {
      const saved = await submitClaim({ ...claim, lines: [{ proc_code, billed }] });
      setMessage(`Claim ${saved.claim_id} saved`);
    } catch (e: any) {
      setMessage(e.message);
    }
  };
  return (
    <main>
      <h1>Submit a claim</h1>
      {Object.entries(form).map(([k, v]) => (
        <p key={k}><label>{k.replace(/_/g, " ")}{" "}
          <input name={k} type={typeof v === "number" ? "number" : "text"} value={v}
            onChange={(e) => setForm({ ...form, [k]: typeof v === "number" ? Number(e.target.value) : e.target.value })} />
        </label></p>))}
      <button onClick={send}>Submit</button>
      <p role="status">{message}</p>
    </main>
  );
}
''',
    "contracts": '''"use client";
import { useEffect, useState } from "react";
import { getContracts, setRate, expire } from "@/Services/ContractsService";

export default function Contracts() {
  const [rows, setRows] = useState<any[]>([]);
  const load = () => getContracts().then(setRows);
  useEffect(() => { load(); }, []);
  const edit = (id: number, rate: number) =>
    setRows(rows.map((k) => (k.contract_id === id ? { ...k, rate_pct: rate } : k)));
  return (
    <main>
      <h1>Provider contracts</h1>
      <table><thead><tr><th>Provider</th><th>Rate %</th><th>Ends</th><th>Status</th><th></th><th></th></tr></thead>
        <tbody>{rows.map((k) => (
          <tr key={k.contract_id}>
            <td>{k.provider_name}</td>
            <td><input type="number" value={k.rate_pct} onChange={(e) => edit(k.contract_id, Number(e.target.value))} /></td>
            <td>{k.end_date}</td><td>{k.status}</td>
            <td><button onClick={() => setRate(k.contract_id, k.rate_pct).then(load)}>Save rate</button></td>
            <td><button onClick={() => expire(k.contract_id).then(load)}>Expire</button></td>
          </tr>))}
        </tbody></table>
    </main>
  );
}
''',
    "payments": '''"use client";
import { useEffect, useState } from "react";
import { getMonthly, getLines } from "@/Services/PaymentsService";

export default function Payments() {
  const [months, setMonths] = useState<any[]>([]);
  const [paymentId, setPaymentId] = useState(1);
  const [lines, setLines] = useState<any[]>([]);
  useEffect(() => { getMonthly().then(setMonths); }, []);
  return (
    <main>
      <h1>Monthly payments</h1>
      <ul>{months.map((m) => <li key={m.month + m.lob}>{m.month} {m.lob} {m.total}</li>)}</ul>
      <label>Payment <input type="number" min={1} value={paymentId} onChange={(e) => setPaymentId(Number(e.target.value))} /></label>
      <button onClick={() => getLines(paymentId).then(setLines)}>Show lines</button>
      <ul>{lines.map((l) => <li key={l.line_id}>{l.proc_code} {l.allowed}</li>)}</ul>
    </main>
  );
}
''',
    "": '''import { redirect } from "next/navigation";

export default function Home() {
  redirect("/claims");
}
''',
}

TIMELINE_COMPONENT = '''export default function StatusTimeline({ steps }: { steps: { status: string; date: string }[] }) {
  return <ol>{steps.map((s) => <li key={s.status}>{s.status} on {s.date}</li>)}</ol>;
}
'''

LAYOUT = '''import Link from "next/link";
import type { ReactNode } from "react";

export const metadata = { title: "Acme Claims" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "sans-serif", margin: 24 }}>
        <nav style={{ display: "flex", gap: 16, marginBottom: 16 }}>
          <b>Acme Claims</b>
          <Link href="/claims">My claims</Link>
          <Link href="/claims/submit">Submit a claim</Link>
          <Link href="/contracts">Contracts</Link>
          <Link href="/payments">Payments</Link>
        </nav>
        {children}
      </body>
    </html>
  );
}
'''

WEB_PACKAGE = """{
  "name": "acme-claims-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "14.2.35",
    "react": "18.3.1",
    "react-dom": "18.3.1"
  },
  "devDependencies": {
    "@types/node": "20.16.15",
    "@types/react": "18.3.19",
    "typescript": "5.6.3"
  }
}
"""

NEXT_CONFIG = '''/** The browser calls /acme/api/...; Next passes the call on to the Django API (ACME_API_URL). */
const API = process.env.ACME_API_URL || "http://127.0.0.1:8000";

module.exports = {
  async rewrites() {
    return [{ source: "/acme/api/:path*", destination: `${API}/acme/api/:path*` }];
  },
};
'''

TSCONFIG = """{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": false,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
"""

NEXT_ENV = '''/// <reference types="next" />
/// <reference types="next/image-types/global" />
'''

RUN_PY = '''#!/usr/bin/env python3
"""Run the Acme Claims sample app on this machine: the API on http://127.0.0.1:8000 and the web app
on http://127.0.0.1:3000, both over a copy of the sandbox's sample.db.

    python3 run.py setup    install the API's Python packages (into .venv) and the web app's npm packages
    python3 run.py          start the API and the web app (Ctrl+C stops both)
    python3 run.py reset    copy the sandbox's sample.db again, dropping what the app changed

Needs Python 3.9+ and Node.js 18+, and pip and npm able to reach a package registry. The database
copy is api/.data/acme.db (ACME_DB to use another file); ACME_API_PORT and ACME_WEB_PORT change the ports.
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
API, WEB, VENV = os.path.join(HERE, "api"), os.path.join(HERE, "web"), os.path.join(HERE, ".venv")
DB = os.environ.get("ACME_DB") or os.path.join(API, ".data", "acme.db")
API_PORT = int(os.environ.get("ACME_API_PORT", "8000"))
WEB_PORT = int(os.environ.get("ACME_WEB_PORT", "3000"))


def venv_python():
    return os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV, "bin", "python")


def npm():
    return shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm"


def sample_db():
    for folder in (os.environ.get("SDLC_SANDBOX"), os.path.dirname(HERE)):
        if folder and os.path.isfile(os.path.join(folder, "sample.db")):
            return os.path.join(folder, "sample.db")
    raise SystemExit("no sample.db found: set SDLC_SANDBOX to the sandbox folder")


def database(reset=False):
    if reset or not os.path.exists(DB):
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        shutil.copyfile(sample_db(), DB)
        print("database: %s" % DB)
    return DB


def setup():
    if not os.path.exists(venv_python()):
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
    subprocess.run([venv_python(), "-m", "pip", "install", "-q", "-r", os.path.join(API, "requirements.txt")], check=True)
    subprocess.run([npm(), "install", "--no-audit", "--no-fund"], cwd=WEB, check=True)
    database()
    print("ready: python3 run.py starts the app")


def start():
    if not os.path.exists(venv_python()) or not os.path.isdir(os.path.join(WEB, "node_modules")):
        raise SystemExit("run `python3 run.py setup` first")
    env = dict(os.environ, ACME_DB=database(), ACME_API_URL="http://127.0.0.1:%d" % API_PORT)
    procs = [subprocess.Popen([venv_python(), "manage.py", "runserver", "127.0.0.1:%d" % API_PORT, "--noreload"],
                              cwd=API, env=env),
             subprocess.Popen([npm(), "run", "dev", "--", "-H", "127.0.0.1", "-p", str(WEB_PORT)], cwd=WEB, env=env)]
    print("API http://127.0.0.1:%d/acme/api/docs  web http://127.0.0.1:%d" % (API_PORT, WEB_PORT))
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
    return max(p.wait() or 0 for p in procs)


def main(argv):
    cmd = argv[0] if argv else "start"
    if cmd == "setup":
        return setup()
    if cmd == "reset":
        database(reset=True)
        return 0
    if cmd == "start":
        return start()
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''

GITIGNORE = ".venv/\n__pycache__/\napi/.data/\nweb/node_modules/\nweb/.next/\n"

APP_README = """# Acme Claims (sample app)

A made-up claims app for the SDLC sandbox: an API (`api/`, Django with Django Ninja), a web front end
(`web/`, Next.js), an admin and a portal front end, and a portal API. The nightly loads are in the
`claims-etl` repo beside this one. The API reads a copy of the sandbox's `sample.db` (SQLite).

## Run it

    python3 run.py setup    # once: Python packages into .venv, npm packages into web/node_modules
    python3 run.py          # API on http://127.0.0.1:8000/acme/api/docs, web app on http://127.0.0.1:3000
    python3 run.py reset    # back to the sandbox's data

It needs Python 3.9+ and Node.js 18+, and pip and npm able to reach a package registry
(PyPI and npm, or your company's mirror).
"""

APP_FILES = {
    "README.md": APP_README,
    ".gitignore": GITIGNORE,
    "run.py": RUN_PY,
    "package.json": '{\n  "name": "acme-claims",\n  "version": "0.1.0",\n  "private": true\n}\n',
    "package-lock.json": '{\n  "name": "acme-claims",\n  "lockfileVersion": 3,\n  "packages": {}\n}\n',
    "api/manage.py": MANAGE_PY,
    "api/requirements.txt": REQUIREMENTS,
    "api/acme/__init__.py": "",
    "api/acme/settings.py": SETTINGS_PY,
    "api/acme/urls.py": URLS_PY,
    "api/apps/__init__.py": "",
    "api/apps/db.py": DB_MODULE,
    "api/apps/app/__init__.py": "",
    "api/apps/app/api.py": API_ROOT,
    "api/apps/claims/__init__.py": "",
    "api/apps/claims/api.py": CLAIMS_API,
    "api/apps/claims/queries.py": CLAIMS_QUERIES,
    "api/apps/claims/schema.py": CLAIMS_SCHEMA,
    "api/apps/contracts/__init__.py": "",
    "api/apps/contracts/api.py": CONTRACTS_API,
    "api/apps/contracts/queries.py": CONTRACTS_QUERIES,
    "api/apps/contracts/schema.py": CONTRACTS_SCHEMA,
    "api/apps/payments/__init__.py": "",
    "api/apps/payments/api.py": PAYMENTS_API,
    "api/apps/payments/queries.py": PAYMENTS_QUERIES,
    "api/apps/payments/schema.py": PAYMENTS_SCHEMA,
    "web/package.json": WEB_PACKAGE,
    "web/next.config.js": NEXT_CONFIG,
    "web/tsconfig.json": TSCONFIG,
    "web/next-env.d.ts": NEXT_ENV,
    "web/src/app/layout.tsx": LAYOUT,
    "web/src/Services/Utility/endpoints.ts": ENDPOINTS_TS,
    "web/src/Services/ClaimsService.ts": CLAIMS_SERVICE,
    "web/src/Services/ContractsService.ts": CONTRACTS_SERVICE,
    "web/src/Services/PaymentsService.ts": PAYMENTS_SERVICE,
    "web/src/_components/StatusTimeline/index.tsx": TIMELINE_COMPONENT,
    "web/microfrontends/claims-intake/index.js": "export { getClaims, submitClaim } from '../../src/Services/ClaimsService';\n",
    "web-admin/contracts.js": "export const contractStatus = (c) => (new Date(c.end_date) > new Date() ? 'active' : "
                              "'expired');\n",
    "web-portal/status.js": "export const statusLabel = (s) => ({paid: 'Paid', pending: 'Pending', denied: "
                            "'Denied'}[s] || s);\n",
    "api-portal/payments.py": 'def monthly_total(db, month):\n    return db.execute("SELECT SUM(PAID_AMT) FROM '
                              'SDLC_PAYMENT WHERE substr(PAID_DT, 1, 7) = ?", (month,)).fetchone()[0] or 0\n',
}
APP_FILES.update({("web/src/app/%s/page.tsx" % route).replace("//", "/"): body for route, body in PAGES.items()})

# ----------------------------------------------------------------------------------------- the ETL

ETL_FILES = {
    "README.md": "# claims-etl (sample)\n\nThe nightly loads of the Acme Claims sample app.\n",
    "scripts/sql/claims_nightly_load.sql": """-- # Title: Claims nightly load
-- # Description: Copies the day's claims and claim lines from the clearinghouse stage into the claims tables.
-- # SourceTables: SDLC_CLAIM_STAGE
-- # TargetTables: SDLC_CLAIM, SDLC_CLAIM_LINE
MERGE INTO {DB_NM}.{SCHMA_NM}.SDLC_CLAIM t
USING (SELECT CLAIM_ID, MEMBER_ID, PROVIDER_ID, CONTRACT_ID, SERVICE_DT, LOB_CD FROM {DB_NM}.{SCHMA_NM}.SDLC_CLAIM_STAGE) s
ON t.CLAIM_ID = s.CLAIM_ID
WHEN NOT MATCHED THEN INSERT (CLAIM_ID, MEMBER_ID, PROVIDER_ID, CONTRACT_ID, SERVICE_DT, STATUS_CD, LOB_CD)
VALUES (s.CLAIM_ID, s.MEMBER_ID, s.PROVIDER_ID, s.CONTRACT_ID, s.SERVICE_DT, 'pending', s.LOB_CD);

INSERT INTO {DB_NM}.{SCHMA_NM}.SDLC_CLAIM_LINE (CLAIM_ID, PROC_CD, BILLED_AMT)
SELECT CLAIM_ID, PROC_CD, BILLED_AMT FROM {DB_NM}.{SCHMA_NM}.SDLC_CLAIM_STAGE;
""",
    "scripts/sql/payments_load.sql": """-- # Title: Payments load
-- # Description: Records the day's payments and marks their claims paid.
-- # SourceTables: SDLC_PAYMENT_STAGE, SDLC_CLAIM
-- # TargetTables: SDLC_PAYMENT, SDLC_CLAIM
INSERT INTO {DB_NM}.{SCHMA_NM}.SDLC_PAYMENT (CLAIM_ID, PAID_DT, PAID_AMT)
SELECT s.CLAIM_ID, s.PAID_DT, s.PAID_AMT
FROM {DB_NM}.{SCHMA_NM}.SDLC_PAYMENT_STAGE s JOIN {DB_NM}.{SCHMA_NM}.SDLC_CLAIM c ON c.CLAIM_ID = s.CLAIM_ID;

UPDATE {DB_NM}.{SCHMA_NM}.SDLC_CLAIM SET STATUS_CD = 'paid'
WHERE CLAIM_ID IN (SELECT CLAIM_ID FROM {DB_NM}.{SCHMA_NM}.SDLC_PAYMENT_STAGE);
""",
    "scripts/sql/contract_expiry.sql": """-- # Title: Contract expiry
-- # Description: Marks contracts whose end date has passed as expired.
-- # SourceTables: SDLC_CONTRACT
-- # TargetTables: SDLC_CONTRACT
UPDATE {DB_NM}.{SCHMA_NM}.SDLC_CONTRACT SET STATUS_CD = 'expired'
WHERE END_DT < CURRENT_DATE AND STATUS_CD = 'active';
""",
    "scripts/python/bank_file.py": '''# Description: Writes the month's payments to the bank file for finance.
QUERY = """
SELECT y.PAYMENT_ID, y.PAID_DT, y.PAID_AMT, c.LOB_CD
FROM SDLC_PAYMENT y JOIN SDLC_CLAIM c ON c.CLAIM_ID = y.CLAIM_ID
WHERE substr(y.PAID_DT, 1, 7) = ?
"""


def main(db, month, out):
    for row in db.execute(QUERY, (month,)):
        out.write(",".join(str(v) for v in row) + "\\n")
''',
}


def write_files(root, files):
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)


# ------------------------------------------------------------------------------- the knowledge base

ENTITIES = [
    ("ENT-01", "Member", "SDLC_MEMBER", "MEMBER_ID", ["member", "patient", "subscriber"], None, [],
     "A person covered by a plan who can submit claims."),
    ("ENT-02", "Provider", "SDLC_PROVIDER", "PROVIDER_ID", ["provider", "clinic", "doctor"], None, ["SDLC_CONTRACT"],
     "A clinic or doctor that treats members and is paid under a contract."),
    ("ENT-03", "Contract", "SDLC_CONTRACT", "CONTRACT_ID", ["contract", "provider contract", "rate table", "rate"],
     ("SDLC_CONTRACT", "STATUS_CD"), [], "The rate a provider is paid, from a start date to an end date."),
    ("ENT-04", "Claim", "SDLC_CLAIM", "CLAIM_ID", ["claim", "claims", "bill", "submission"],
     ("SDLC_CLAIM", "STATUS_CD"), ["SDLC_CLAIM_LINE", "SDLC_PAYMENT"],
     "A request to pay for a member's care, with one or more lines."),
    ("ENT-05", "Claim line", "SDLC_CLAIM_LINE", "LINE_ID", ["claim line", "line", "procedure"], None, [],
     "One billed procedure on a claim, with what was billed and what is allowed."),
    ("ENT-06", "Payment", "SDLC_PAYMENT", "PAYMENT_ID", ["payment", "paid", "remittance", "bank file"], None, [],
     "Money paid for a claim, on a date."),
]

STATES = {
    "claim_status": {"description": "SDLC_CLAIM.STATUS_CD", "values": {"pending": "Submitted, not decided yet",
                                                                       "paid": "Paid; a payment row exists",
                                                                       "denied": "Refused; nothing is paid"},
                     "flow": "pending -> paid | denied"},
    "contract_status": {"description": "SDLC_CONTRACT.STATUS_CD", "values": {"active": "Pays claims",
                                                                             "expired": "End date passed; pays nothing"},
                        "flow": "active -> expired"},
}

ROUTING = [
    {"id": "claim_submission", "intent": "Submitting a claim and its documents", "module": "claims",
     "triggers": ["submit", "submission", "upload", "attachment", "document", "new claim", "draft", "receipt"],
     "tables_to_modify": [{"table": "SDLC_CLAIM", "mandatory_columns": ["MEMBER_ID", "PROVIDER_ID", "SERVICE_DT"]},
                          {"table": "SDLC_CLAIM_LINE", "mandatory_columns": ["CLAIM_ID", "PROC_CD", "BILLED_AMT"]}],
     "api_endpoints": ["/api/claims/submit"], "etl_scripts": ["claims_nightly_load.sql"],
     "ui_screens": ["/claims/submit"], "downstream_jobs": ["payments_load.sql"],
     "change_risk": "MEDIUM - a new claim column must be loaded by the nightly load as well"},
    {"id": "eligibility", "intent": "Checking that a member has an active plan", "module": "claims",
     "triggers": ["eligib", "active plan", "coverage", "member without"],
     "tables_to_modify": [{"table": "SDLC_MEMBER", "mandatory_columns": ["MEMBER_ID", "PLAN_CD"]}],
     "api_endpoints": ["/api/claims/submit"], "etl_scripts": [], "ui_screens": ["/claims/submit"],
     "downstream_jobs": [], "change_risk": "MEDIUM - refusing a claim changes what members can submit"},
    {"id": "claim_status", "intent": "Claim status and the status timeline", "module": "claims",
     "triggers": ["status", "timeline", "my claims", "pending", "denied"],
     "tables_to_modify": [{"table": "SDLC_CLAIM", "mandatory_columns": ["CLAIM_ID", "STATUS_CD"]}],
     "api_endpoints": ["/api/claims/list", "/api/claims/timeline"], "etl_scripts": ["payments_load.sql"],
     "ui_screens": ["/claims"], "downstream_jobs": ["bank_file.py"],
     "change_risk": "HIGH - the payments load sets claims to paid; a new status must be handled there"},
    {"id": "contract_rates", "intent": "Provider contracts and their rates", "module": "contracts",
     "triggers": ["contract", "rate", "provider", "expire", "expiry", "rate table"],
     "tables_to_modify": [{"table": "SDLC_CONTRACT", "mandatory_columns": ["CONTRACT_ID", "PROVIDER_ID", "RATE_PCT",
                                                                           "START_DT", "END_DT"]}],
     "api_endpoints": ["/api/contracts/list", "/api/contracts/rate", "/api/contracts/expire"],
     "etl_scripts": ["contract_expiry.sql"], "ui_screens": ["/contracts"], "downstream_jobs": [],
     "change_risk": "HIGH - the rate decides what every claim under the contract pays"},
    {"id": "payment_reporting", "intent": "Payment reports, bank file and reconciliation", "module": "payments",
     "triggers": ["payment", "paid", "report", "month", "line of business", "bank", "reconcil", "finance"],
     "tables_to_modify": [{"table": "SDLC_PAYMENT", "mandatory_columns": ["PAYMENT_ID", "CLAIM_ID", "PAID_DT",
                                                                          "PAID_AMT"]}],
     "api_endpoints": ["/api/payments/monthly", "/api/payments/lines"], "etl_scripts": ["payments_load.sql",
                                                                                         "bank_file.py"],
     "ui_screens": ["/payments"], "downstream_jobs": ["bank_file.py"],
     "change_risk": "HIGH - finance reconciles the bank file against these totals"},
]

CHAINS = [
    {"chain_id": "DC-01", "db_table": "SDLC_CLAIM", "db_column": "STATUS_CD", "business_name": "Claim status",
     "change_impact": "high",
     "writers": [{"layer": "API", "endpoint": "POST /api/claims/submit", "action": "writes pending"},
                 {"layer": "ETL", "script": "claims_nightly_load.sql", "action": "writes pending for loaded claims"},
                 {"layer": "ETL", "script": "payments_load.sql", "action": "sets paid"}],
     "readers": [{"layer": "UI", "component": "/claims", "action": "shows the status and the timeline"},
                 {"layer": "API", "endpoint": "GET /api/claims/timeline", "action": "reads each status"}],
     "if_changed": [{"layer": "DB", "action": "Add the new value to claim_status in 09_DB_SEMANTIC_LAYER.yaml",
                     "effort": "low"},
                    {"layer": "ETL", "action": "Check payments_load.sql still sets paid only for paid claims",
                     "effort": "low"},
                    {"layer": "UI", "action": "Show the new value on the status timeline", "effort": "low"}]},
    {"chain_id": "DC-02", "db_table": "SDLC_CONTRACT", "db_column": "RATE_PCT", "business_name": "Contract rate",
     "change_impact": "high",
     "writers": [{"layer": "API", "endpoint": "PUT /api/contracts/rate", "action": "updates the rate"}],
     "readers": [{"layer": "UI", "component": "/contracts", "action": "shows and edits the rate"},
                 {"layer": "ETL", "script": "payments_load.sql", "action": "pays claims at the rate"}],
     "if_changed": [{"layer": "DB", "action": "Keep an audit trail of rate changes", "effort": "medium"},
                    {"layer": "ETL", "action": "Recheck payments made after the change", "effort": "medium"}]},
    {"chain_id": "DC-03", "db_table": "SDLC_PAYMENT", "db_column": "PAID_AMT", "business_name": "Amount paid",
     "change_impact": "high",
     "writers": [{"layer": "ETL", "script": "payments_load.sql", "action": "inserts the day's payments"}],
     "readers": [{"layer": "API", "endpoint": "GET /api/payments/monthly", "action": "sums by month"},
                 {"layer": "ETL", "script": "bank_file.py", "action": "writes the bank file"},
                 {"layer": "Downstream", "systems": ["BANK"], "action": "reconciles the file"}],
     "if_changed": [{"layer": "Downstream", "action": "Tell finance before the next bank file", "effort": "low"},
                    {"layer": "API", "action": "Rerun the monthly report for open months", "effort": "low"}]},
]

DOMAIN_CONTEXT = """# Domain context: Acme Claims (sandbox)

Acme Claims is a made-up health claims product used to try the SDLC framework. Nothing in it is real.

## What it does
Members (people covered by a plan) and providers (clinics and doctors) submit claims for care. The app checks
that the member has an active plan, saves the claim and its lines, and shows the member each status change.
Contract managers keep each provider's contract: the rate it pays and its start and end dates. Finance sees
what was paid each month by line of business and sends the bank file.

## Modules
| Module | Screens | API | Tables |
|---|---|---|---|
| Claims intake | `/claims`, `/claims/submit` | `/api/claims/*` | `SDLC_CLAIM`, `SDLC_CLAIM_LINE`, `SDLC_MEMBER` |
| Provider contracts | `/contracts` | `/api/contracts/*` | `SDLC_CONTRACT`, `SDLC_PROVIDER` |
| Payment reporting | `/payments` | `/api/payments/*` | `SDLC_PAYMENT` |

## Words people use
| Word | Means | Where it lives |
|---|---|---|
| Claim | a request to pay for a member's care | `SDLC_CLAIM` |
| Claim line | one billed procedure on a claim | `SDLC_CLAIM_LINE` |
| Eligible, active plan | the member has a plan (`PLAN_CD` set) | `SDLC_MEMBER.PLAN_CD` |
| Status | pending, paid or denied | `SDLC_CLAIM.STATUS_CD` |
| Rate, rate table | the percentage a contract pays | `SDLC_CONTRACT.RATE_PCT` |
| Expired contract | end date passed; pays nothing | `SDLC_CONTRACT.STATUS_CD` |
| Line of business (LOB) | Commercial, Medicare or Medicaid | `SDLC_CLAIM.LOB_CD` |
| Bank file | the month's payments sent to the bank | `claims-etl/scripts/python/bank_file.py` |

## Systems around it
- The clearinghouse sends claims each night into `SDLC_CLAIM_STAGE`; `claims_nightly_load.sql` loads them.
- The payment system sends payments each night into `SDLC_PAYMENT_STAGE`; `payments_load.sql` loads them.
- The bank receives the bank file each month and finance reconciles it with the monthly report.

## Data rules
- Member names and birth year are personal health information: never in logs, reports or test data copied
  out of the sandbox.
- A claim is paid only under an active contract.
"""

API_BRD = """# Acme Claims API: business requirements (sample)

| Id | Requirement | Endpoint |
|---|---|---|
| BR-1 | A signed-in member can submit a claim with one or more lines. | `POST /api/claims/submit` |
| BR-2 | A claim for a member without an active plan is refused with a plain message. | `POST /api/claims/submit` |
| BR-3 | The member sees their claims and each status change with its date. | `GET /api/claims/list`, `GET /api/claims/timeline` |
| BR-4 | A contract manager can change a contract's rate and expire a contract. | `PUT /api/contracts/rate`, `POST /api/contracts/expire` |
| BR-5 | Finance sees what was paid each month by line of business, and the lines behind a payment. | `GET /api/payments/monthly`, `GET /api/payments/lines` |
"""


def kb_files(counts):
    """Path inside the KB folder -> text, for the files a team keeps by hand."""
    cols = {t: [{"name": n, "type": d.split()[0], "nullable": "PRIMARY KEY" not in d} for n, d in c]
            for t, c in COLUMNS.items()}
    registry = {"database": DB, "schema": SCHEMA, "tables": [
        {"name": t, "layer": "base", "module": MODULE[t], "status": "active", "pk": [COLUMNS[t][0][0]],
         "rows": counts.get(t, 0), "columns": cols[t]} for t in COLUMNS] + [
        {"name": t, "layer": "staging", "module": MODULE[t], "status": "active", "description": d,
         "columns": [{"name": "CLAIM_ID", "type": "INTEGER", "nullable": False}]} for t, d in STAGE_TABLES.items()]}
    entities = {"entities": [
        dict({"entity_id": i, "canonical_name": n, "canonical_table": t, "canonical_key": k, "aliases": a,
              "related_tables": r, "description": d, "confidence": "high", "source": "sandbox sample"},
             **({"status_location": {"table": s[0], "column": s[1]}} if s else {}))
        for i, n, t, k, a, s, r, d in ENTITIES],
        "code_aliases": [
            {"alias_id": "ALIAS-01", "user_phrase": ["eligible member", "active plan", "has coverage"],
             "resolves_to": {"table": "SDLC_MEMBER", "column": "PLAN_CD", "value": "not null"},
             "sql_snippet": "WHERE PLAN_CD IS NOT NULL"},
            {"alias_id": "ALIAS-02", "user_phrase": ["expired contract", "contract ended"],
             "resolves_to": {"table": "SDLC_CONTRACT", "column": "STATUS_CD", "value": "expired"},
             "sql_snippet": "WHERE STATUS_CD = 'expired'"},
            {"alias_id": "ALIAS-03", "user_phrase": ["paid claim", "claims paid"],
             "resolves_to": {"table": "SDLC_CLAIM", "column": "STATUS_CD", "value": "paid"},
             "sql_snippet": "WHERE STATUS_CD = 'paid'"}]}
    semantic = {
        "entities": {n.lower().replace(" ", "_"): {"primary_table": t, "display_name": n, "related_tables": r}
                     for _i, n, t, _k, _a, _s, r, _d in ENTITIES},
        "guardrails": {
            "entity_aliases": {n.lower().replace(" ", "_"): {"aliases": a} for _i, n, _t, _k, a, _s, _r, _d in ENTITIES},
            "mandatory_filters": ["Read a member's claims only with that member's MEMBER_ID"],
            "forbidden_actions": ["Never delete a claim, a claim line or a payment"],
            "query_rules": ["Join claims to providers on PROVIDER_ID and to payments on CLAIM_ID"],
            "response_rules": ["Never show member names or birth year outside the claims screens"]},
        "joins": [
            {"name": "claim to member", "left_table": "SDLC_CLAIM", "right_table": "SDLC_MEMBER",
             "join_key": "MEMBER_ID", "cardinality": "many-to-one"},
            {"name": "claim to provider", "left_table": "SDLC_CLAIM", "right_table": "SDLC_PROVIDER",
             "join_key": "PROVIDER_ID", "cardinality": "many-to-one"},
            {"name": "claim to contract", "left_table": "SDLC_CLAIM", "right_table": "SDLC_CONTRACT",
             "join_key": "CONTRACT_ID", "cardinality": "many-to-one"},
            {"name": "contract to provider", "left_table": "SDLC_CONTRACT", "right_table": "SDLC_PROVIDER",
             "join_key": "PROVIDER_ID", "cardinality": "many-to-one"},
            {"name": "line to claim", "left_table": "SDLC_CLAIM_LINE", "right_table": "SDLC_CLAIM",
             "join_key": "CLAIM_ID", "cardinality": "many-to-one"},
            {"name": "payment to claim", "left_table": "SDLC_PAYMENT", "right_table": "SDLC_CLAIM",
             "join_key": "CLAIM_ID", "cardinality": "many-to-one"}],
        "value_dictionaries": STATES}
    lineage = {
        "internal_flows": [{"flow_id": "FLOW-01", "name": "Claim to payment",
                            "description": "A claim is submitted or loaded as pending, then paid by the payments load.",
                            "stages": [{"stage": "submit", "tables": ["SDLC_CLAIM", "SDLC_CLAIM_LINE"],
                                        "trigger": "POST /api/claims/submit or claims_nightly_load.sql",
                                        "status_written": "pending"},
                                       {"stage": "pay", "tables": ["SDLC_PAYMENT", "SDLC_CLAIM"],
                                        "trigger": "payments_load.sql", "status_written": "paid"}],
                            "confidence": "high"}],
        "phi_flows": [{"source_table": "SDLC_MEMBER", "phi_column_example": "BIRTH_YR", "masked_in": "reports",
                       "unmasked_in": "claims API", "masking_policy": "none in the sandbox"}],
        "inbound_flows": [
            {"flow_id": "IN-01", "name": "Clearinghouse claims", "source_system": "Clearinghouse",
             "target_tables": ["SDLC_CLAIM_STAGE"], "trigger": "nightly", "confidence": "high"},
            {"flow_id": "IN-02", "name": "Payment system payments", "source_system": "Payment system",
             "target_tables": ["SDLC_PAYMENT_STAGE"], "trigger": "nightly", "confidence": "high"}],
        "outbound_flows": [{"flow_id": "OUT-01", "name": "Bank file", "consumer_system": "BANK",
                            "consumer_full_name": "The bank", "source_tables": ["SDLC_PAYMENT", "SDLC_CLAIM"],
                            "trigger": "monthly", "note": "Finance reconciles it with the monthly report.",
                            "confidence": "high"}],
        "open_questions": [{"id": "LIN-Q1", "question": "Does a denied claim ever become paid later, and if so "
                            "which job changes it?", "assigned_to": "DB lead", "impact": "medium"}]}
    contracts = {"tables": [
        {"table": "SDLC_CLAIM", "contracts": [
            {"column": "STATUS_CD", "api_field": "status", "fe_display": "Status", "fe_location": "/claims",
             "validation": "pending | paid | denied"},
            {"column": "SERVICE_DT", "api_field": "service_date", "fe_display": "Date of service",
             "fe_location": "/claims/submit", "validation": "not in the future"}]},
        {"table": "SDLC_CONTRACT", "contracts": [
            {"column": "RATE_PCT", "api_field": "rate_pct", "fe_display": "Rate", "fe_location": "/contracts",
             "validation": "0 to 100"}]}]}
    glossary = {"entries": [{"table": "SDLC_MEMBER", "columns": {
        "FIRST_NM": {"pii_phi": True, "description": "first name"},
        "LAST_NM": {"pii_phi": True, "description": "last name"},
        "BIRTH_YR": {"pii_phi": True, "description": "year of birth"}}}]}
    patterns = {"patterns": [
        {"id": "PAT-01", "name": "Merge from a stage table", "used_by": ["claims_nightly_load.sql"]},
        {"id": "PAT-02", "name": "Insert then update the parent status", "used_by": ["payments_load.sql"]}],
        "open_questions": []}
    curated = {"dependency_chains": CHAINS, "table_impact_summary": [
        {"table": "SDLC_CLAIM", "risk": "high", "note": "read by every module"},
        {"table": "SDLC_CONTRACT", "risk": "high", "note": "the rate decides payments"},
        {"table": "SDLC_PAYMENT", "risk": "high", "note": "feeds the bank file"}]}

    def y(data, title):
        return "# %s (sandbox sample, made up)\n" % title + yaml.safe_dump(data, sort_keys=False, width=110)

    return {
        "DB-DOCS/DB_TABLE_REGISTRY.yaml": y(registry, "Tables of the sample database"),
        "DB-DOCS/13_DB_ENTITY_REGISTRY.yaml": y(entities, "Business entities and the tables behind them"),
        "DB-DOCS/09_DB_SEMANTIC_LAYER.yaml": y(semantic, "Semantic layer"),
        "DB-DOCS/11_DB_DATA_LINEAGE.yaml": y(lineage, "Data lineage"),
        "DB-DOCS/11_DB_DATA_CONTRACTS.yaml": y(contracts, "Data contracts: column to API field to screen"),
        "DB-DOCS/15_CFF_TABLE_CATALOGUE.yaml": y({"tables": []}, "Configuration workbook catalogue (none here)"),
        "DB-DOCS/DB_COLUMN_GLOSSARY.yaml": y(glossary, "Column glossary"),
        "DB-DOCS/16_REQUIREMENT_ROUTING_MAP.yaml": y({"routing_entries": ROUTING}, "Requirement routing map"),
        "ETL/claims-etl/12_ETL_SQL_PATTERNS.yaml": y(patterns, "ETL SQL patterns"),
        "CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.CURATED.yaml": y(curated, "Curated impact chains"),
        "SHARED/DOMAIN_CONTEXT.md": DOMAIN_CONTEXT,
        "MODULES/claims-web/api/01_BUSINESS_REQUIREMENTS.md": API_BRD,
    }


# ------------------------------------------------------------------------------- building the KB

def build_kb(repo, sdlc_dir="sdlc", etl_repo=None):
    """Run the KB generators of the framework installed in `repo` on the sample app.
    Returns [(step, ok, last line of output)] up to the first failed step; later steps read what it
    writes, so they are not run."""
    tools = os.path.join(repo, sdlc_dir, "framework", "tools")
    gen = os.path.join(tools, "kbgen")
    env = dict(os.environ, SDLC_ETL_REPO=etl_repo or os.path.join(os.path.dirname(repo), "claims-etl"))
    env.pop("SDLC_KB_OUT", None)
    fd, api_json = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    steps = [
        ("API extract", [os.path.join(gen, "extract_api.py")], api_json),
        ("endpoint registry", [os.path.join(gen, "gen_api_kb.py"), api_json], None),
        ("component registry", [os.path.join(gen, "gen_ui_kb.py")], None),
        ("ETL table I/O", [os.path.join(gen, "gen_etl_kb.py")], None),
        ("app joins", [os.path.join(gen, "extract_app_joins.py")], None),
        ("cross-layer matrix", [os.path.join(gen, "gen_cross_module_matrix.py")], None),
        ("ontology", [os.path.join(gen, "gen_ontology.py")], None),
        ("link graph", [os.path.join(gen, "gen_link_graph.py")], None),
        ("KB manifest", [os.path.join(tools, "kb_manifest.py"), "generate"], None),
    ]
    out = []
    try:
        for name, args, stdout_to in steps:
            r = subprocess.run([sys.executable] + args, cwd=repo, env=env, capture_output=True, text=True)
            if stdout_to and r.returncode == 0:
                with open(stdout_to, "w", encoding="utf-8") as fh:
                    fh.write(r.stdout)
            text = (r.stderr if r.returncode else r.stdout).strip().splitlines()
            out.append((name, r.returncode == 0, text[-1] if text and not stdout_to or r.returncode else ""))
            if r.returncode:
                break
    finally:
        os.remove(api_json)
    return out
