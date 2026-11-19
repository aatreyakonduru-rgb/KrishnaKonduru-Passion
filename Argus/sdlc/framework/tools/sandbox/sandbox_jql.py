"""The part of Jira's query language the framework uses, run over the sandbox's issues.

    match(jql, issue, ctx) -> bool          order(jql) -> [(field, descending)]

Clauses: project, key/issuekey, status, statusCategory, issuetype/type, assignee, reporter, labels,
resolution, priority, parent, sprint, "IT Team" (and any custom field by name, id or cf[n]),
summary/description/text ~, created/updated/resolved/resolutiondate with dates or -Nd/-Nw/-Nh.
Operators =, !=, in, not in, ~, !~, is, is not, >, >=, <, <=; AND, OR, NOT and brackets; functions
openSprints(), closedSprints(), futureSprints(), currentUser(), now(), startOfDay(), EMPTY/null.
A clause on a field the sandbox doesn't know is true, so a query still returns something.
"""
import datetime
import re

LEXEME = re.compile(r"""\s*(?:(?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(?P<op>!=|>=|<=|!~|=|~|>|<|\(|\)|,)|(?P<word>[^\s=!~<>(),"']+))""")
KEYWORDS = {"and", "or", "not", "in", "is", "empty", "null", "order", "by", "asc", "desc"}


class JqlError(ValueError):
    pass


def tokens(text):
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = LEXEME.match(text, pos)
        if not m or m.end() == pos:
            raise JqlError("cannot read the query at: %s" % text[pos:pos + 30])
        pos = m.end()
        if m.group("str") is not None:
            raw = m.group("str")[1:-1]
            out.append(("str", re.sub(r"\\(.)", r"\1", raw)))
        elif m.group("op") is not None:
            out.append(("op", m.group("op")))
        else:
            out.append(("word", m.group("word")))
    return out


def split_order(jql):
    m = re.search(r"\border\s+by\b", jql, re.I)
    return (jql[:m.start()], jql[m.end():]) if m else (jql, "")


def order(jql):
    rest = split_order(jql)[1]
    out = []
    for part in [p.strip() for p in rest.split(",") if p.strip()]:
        bits = part.rsplit(None, 1)
        desc = len(bits) == 2 and bits[1].lower() == "desc"
        name = bits[0] if len(bits) == 2 and bits[1].lower() in ("asc", "desc") else part
        out.append((name.strip().strip('"').lower(), desc))
    return out


class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def word(self, w, k=0):
        kind, val = self.peek(k)
        return kind == "word" and val.lower() == w

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            return ("true",)
        node = self.expr()
        if self.i < len(self.t):
            raise JqlError("unexpected %r" % (self.peek()[1],))
        return node

    def expr(self):
        node = self.term()
        while self.word("or"):
            self.take()
            node = ("or", node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.word("and"):
            self.take()
            node = ("and", node, self.factor())
        return node

    def factor(self):
        if self.word("not"):
            self.take()
            return ("not", self.factor())
        if self.peek() == ("op", "("):
            self.take()
            node = self.expr()
            if self.take() != ("op", ")"):
                raise JqlError("missing )")
            return node
        return self.clause()

    def clause(self):
        kind, field = self.take()
        if kind not in ("word", "str"):
            raise JqlError("expected a field, got %r" % field)
        if self.word("not") and self.word("in", 1):
            self.i += 2
            return ("clause", field, "not in", self.values())
        if self.word("in"):
            self.take()
            return ("clause", field, "in", self.values())
        if self.word("is"):
            self.take()
            neg = self.word("not")
            if neg:
                self.take()
            self.take()
            return ("clause", field, "is not" if neg else "is", None)
        kind, op = self.take()
        if kind != "op" or op not in ("=", "!=", "~", "!~", ">", ">=", "<", "<="):
            raise JqlError("expected an operator after %s" % field)
        return ("clause", field, op, self.value())

    def values(self):
        if self.peek() != ("op", "("):
            return [self.value()]
        self.take()
        out = []
        while self.peek() != ("op", ")"):
            if self.peek()[0] is None:
                raise JqlError("missing )")
            if self.peek() == ("op", ","):
                self.take()
                continue
            out.append(self.value())
        self.take()
        return out

    def value(self):
        kind, val = self.take()
        if kind is None:
            raise JqlError("missing a value")
        if kind == "word" and self.peek() == ("op", "("):
            self.take()
            args = []
            while self.peek() != ("op", ")"):
                if self.peek()[0] is None:
                    raise JqlError("missing )")
                k, a = self.take()
                if (k, a) != ("op", ","):
                    args.append(a)
            self.take()
            return ("fn", val.lower(), args)
        if kind == "word" and val.lower() in ("empty", "null"):
            return ("empty",)
        return ("lit", val)


def parse(jql):
    return Parser(tokens(split_order(jql)[0])).parse()


def when(text):
    """A date in a query: 2026-10-01, "2026-10-01 10:00", -5d, -2w, -3h, now()."""
    text = str(text).strip()
    m = re.fullmatch(r"([+-]?)(\d+)([mhdw])", text)
    if m:
        n = int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
        unit = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[m.group(3)]
        return datetime.datetime.now() + datetime.timedelta(**{unit: n})
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def stamp(text):
    if not text:
        return None
    try:
        return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return when(str(text)[:10])


DATE_FIELDS = {"created": "created", "createddate": "created", "updated": "updated", "updateddate": "updated",
               "resolved": "resolutiondate", "resolutiondate": "resolutiondate", "duedate": "duedate", "due": "duedate"}
TEXT_FIELDS = {"summary": ("summary",), "description": ("description",), "comment": ("comment",),
               "text": ("summary", "description", "comment")}


def resolve(value, ctx):
    """[str, ...] for a value node, with functions expanded."""
    kind = value[0]
    if kind == "lit":
        return [value[1]]
    if kind == "empty":
        return [None]
    name = value[1]
    if name == "currentuser":
        return [ctx.get("user")]
    if name in ("opensprints", "closedsprints", "futuresprints"):
        state = {"opensprints": "active", "closedsprints": "closed", "futuresprints": "future"}[name]
        return ["#sprint:%s" % s["id"] for s in ctx.get("sprints", []) if s.get("state") == state]
    if name in ("now",):
        return ["0m"]
    if name in ("startofday", "startofweek", "startofmonth"):
        return [datetime.date.today().isoformat()]
    if name in ("membersof",):
        return ["#group:%s" % (value[2][0] if value[2] else "")]
    return [None]


def values_of(field, issue, ctx):
    """What the issue holds for a field, as a list of comparable strings (lower case)."""
    f = field.lower()
    data = issue
    if f in ("project",):
        return [issue["key"].split("-")[0].lower(), (ctx.get("project_name") or "").lower()]
    if f in ("key", "issuekey", "id"):
        return [issue["key"].lower()]
    if f in ("status",):
        return [str(data.get("status") or "").lower()]
    if f in ("statuscategory",):
        return [ctx["category"](data.get("status")).lower()]
    if f in ("issuetype", "type"):
        return [str(data.get("issuetype") or "").lower()]
    if f in ("assignee", "reporter", "creator"):
        who = data.get("assignee" if f == "assignee" else "reporter")
        if not who:
            return [None]
        user = ctx["user_of"](who) or {}
        return [str(who).lower(), str(user.get("displayName", "")).lower(), str(user.get("emailAddress", "")).lower()]
    if f in ("labels", "label"):
        return [str(x).lower() for x in data.get("labels") or []] or [None]
    if f in ("resolution",):
        return [str(data.get("resolution")).lower()] if data.get("resolution") else ["unresolved", None]
    if f in ("priority",):
        return [str(data.get("priority") or "").lower()] if data.get("priority") else [None]
    if f in ("parent", "epic link", "\"epic link\"", "parentepic"):
        return [str(data.get("parent")).lower()] if data.get("parent") else [None]
    if f in ("sprint",):
        ids = data.get("sprints") or []
        out = []
        for sid in ids:
            s = ctx["sprint"](sid) or {}
            out += ["#sprint:%s" % sid, str(sid), str(s.get("name", "")).lower()]
        return out or [None]
    if f in ("fixversion", "fixversions"):
        return [str(x).lower() for x in data.get("fix_versions") or []] or [None]
    if f in ("component", "components"):
        return [str(x).lower() for x in data.get("components") or []] or [None]
    cf = ctx["custom"](field)
    if cf:
        v = (data.get("fields") or {}).get(cf)
        if v is None:
            return [None]
        if isinstance(v, list):
            return [str(x.get("value", x) if isinstance(x, dict) else x).lower() for x in v]
        if isinstance(v, dict):
            return [str(v.get("value", v.get("name", ""))).lower()]
        return [str(v).lower()]
    return ["#unknown"]


def text_of(field, issue):
    parts = []
    for name in TEXT_FIELDS[field.lower()]:
        if name == "comment":
            parts += [c.get("body", "") for c in issue.get("comments") or []]
        else:
            parts.append(issue.get(name) or "")
    return " ".join(parts).lower()


def compare_dates(field, op, value, issue, ctx):
    have = stamp(issue.get(DATE_FIELDS[field.lower()]))
    want = None
    for v in resolve(value, ctx):
        want = when(v) if v is not None else None
    if want is None:
        return op in ("is", "!=") and have is None
    if have is None:
        return False
    return {">": have > want, ">=": have >= want, "<": have < want, "<=": have <= want,
            "=": have.date() == want.date(), "!=": have.date() != want.date()}.get(op, True)


def clause(node, issue, ctx):
    _, field, op, value = node
    f = field.lower()
    if f in TEXT_FIELDS and op in ("~", "!~"):
        words = [w for w in re.findall(r"\w+", str(resolve(value, ctx)[0] or "").lower())]
        hit = all(w in text_of(f, issue) for w in words)
        return hit if op == "~" else not hit
    if f in DATE_FIELDS and op not in ("is", "is not", "in", "not in"):
        return compare_dates(f, op, value, issue, ctx)
    have = values_of(field, issue, ctx)
    if have == ["#unknown"]:
        ctx.setdefault("unknown", set()).add(field)
        return True
    if op in ("is", "is not"):
        empty = have == [None] or (f == "resolution" and "unresolved" in have)
        return empty if op == "is" else not empty
    wanted = []
    for v in (value if isinstance(value, list) else [value]):
        wanted += resolve(v, ctx)
    wanted = [w.lower() if isinstance(w, str) else w for w in wanted]
    if f == "resolution":
        wanted = [None if w in ("unresolved", None) else w for w in wanted]
        have = [None] if not issue.get("resolution") else have
    hit = any(w in have for w in wanted)
    if op in ("=", "in", "~"):
        return hit
    if op in ("!=", "not in", "!~"):
        return not hit and have != [None] if f not in ("resolution",) else not hit
    if op in (">", ">=", "<", "<="):
        try:
            a, b = float(have[0]), float(wanted[0])
        except (TypeError, ValueError):
            return False
        return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]
    return True


def evaluate(node, issue, ctx):
    kind = node[0]
    if kind == "true":
        return True
    if kind == "and":
        return evaluate(node[1], issue, ctx) and evaluate(node[2], issue, ctx)
    if kind == "or":
        return evaluate(node[1], issue, ctx) or evaluate(node[2], issue, ctx)
    if kind == "not":
        return not evaluate(node[1], issue, ctx)
    return clause(node, issue, ctx)


def match(jql, issue, ctx):
    return evaluate(parse(jql), issue, ctx)
