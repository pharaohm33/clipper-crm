#!/usr/bin/env python3
"""
Who the email says "Hey ___" to.

  - the portal gave a contact name ("Sophia")                     -> that first name
  - the address is a role or brand mailbox (info@, support@ ...)  -> the business name
  - anything else (sophia@, claire@, bummer@, letschat@ ...)      -> DeepSeek says whether the part before the @ is a person's first name;
                                                                    if it is, that name, otherwise the business name

DeepSeek is never trusted to invent a name: the name it returns must be the address's own text (or start with it), and when DeepSeek is
unreachable the business name is used.
"""
import html
import json
import re
import urllib.request

import personalize

ROLE = {"info", "support", "hello", "hi", "hey", "contact", "contactus", "sales", "team", "admin", "office", "orders", "order", "help", "customerservice",
        "customercare", "customersupport", "care", "service", "services", "marketing", "media", "press", "pr", "publicrelations", "enquiries", "enquiry",
        "inquiries", "inquiry", "mail", "store", "shop", "accounts", "accounting", "billing", "hr", "jobs", "careers", "wholesale", "returns", "feedback",
        "general", "reception", "webmaster", "web", "online", "ecommerce", "partnerships", "partners", "advertising", "ads", "social", "news", "newsletter",
        "bookings", "booking", "reservations", "appointments", "questions", "hola", "kontakt", "bonjour", "ciao", "post", "mailbox", "operations", "ops",
        "digital", "brand", "customer", "client", "clients", "members", "membership", "events", "design", "studio", "retail", "trade", "dealers", "export"}
LEGAL = re.compile(r"[,\s]+(inc\.?|llc\.?|l\.l\.c\.?|ltd\.?|limited|corp\.?|corporation|co\.?|company|pty\.? ?ltd\.?|pty|gmbh|plc|llp|lp|s\.a\.?|sarl|bv|ag|usa|us)\.?$", re.I)


def clean_business(name):
    n = html.unescape(str(name or "")).replace("&quot", " ")
    n = re.sub(r"\s+", " ", n).strip(" ,.-")
    for _ in range(3):
        m = LEGAL.search(n)
        if m and len(n) > m.end() - m.start() + 2:
            n = n[:m.start()].strip(" ,.-")
    return n or "your company"


def _person_first(person):
    p = re.sub(r"\s+", " ", str(person or "")).strip()
    if not p or re.search(r"owner|operator|team|support|admin|\d|@", p, re.I):
        return ""
    first = p.split(" ")[0]
    return first[:1].upper() + first[1:] if re.fullmatch(r"[A-Za-z][A-Za-z'’\-]{1,20}", first) else ""


def _local(email):
    return str(email or "").split("@")[0].lower()


def _chat(system, user, timeout=60):
    key = personalize.deepseek_key()
    if not key:
        return ""
    body = json.dumps({"model": personalize.MODEL, "temperature": 0, "max_tokens": 1500,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(personalize.URL, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception:
        return ""


SYSTEM = """For each item you get an email address and the company it belongs to. Decide whether the part before the @ is a PERSON'S FIRST NAME (or a first name followed by a last name or initial, like sophia, john.smith, jsmith is NOT a first name).
A brand mailbox, a role, a product word, a phrase or a nickname is NOT a person: bummer, letschat, getbeer, consignthedress, hello, support, shopping are not people.
Reply with ONLY a JSON object mapping each id to the first name in normal capitalisation if the local part is clearly a person's first name, or to "" if not or if you are unsure. Never invent a name that is not in the address."""


def resolve(items):
    """items: [{id, email, company, person}] -> {id: {'first': greeting, 'kind': 'person'|'business', 'business': cleaned company}}"""
    out, ask = {}, []
    for it in items:
        biz = clean_business(it.get("company"))
        res = {"first": biz, "kind": "business", "business": biz}
        name = _person_first(it.get("person"))
        local = _local(it.get("email"))
        base = re.sub(r"[^a-z]", "", local)
        if name:
            res.update(first=name, kind="person")
        elif base in ROLE or not re.search(r"[a-z]{2}", local) or re.search(r"\d", local) and len(base) < 3:
            pass
        else:
            ask.append((it["id"], local, biz, it.get("email")))
        out[it["id"]] = res
    for i in range(0, len(ask), 40):
        chunk = ask[i:i + 40]
        raw = _chat(SYSTEM, "\n".join(f"{id_}: {email} (company: {biz})" for id_, _l, biz, email in chunk))
        try:
            got = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception:
            got = {}
        for id_, local, biz, email in chunk:
            cand = re.sub(r"\s+", " ", str(got.get(id_) or "")).strip()
            first = re.split(r"[._\-]", local)[0]
            # the name must really be in the address, so a guess can never slip through
            if re.fullmatch(r"[A-Za-z][A-Za-z'’\-]{1,20}", cand) and re.sub(r"[^a-z]", "", cand.lower()) and re.sub(r"[^a-z]", "", cand.lower()) in re.sub(r"[^a-z]", "", local) and local.replace(".", "").replace("_", "").replace("-", "").startswith(re.sub(r"[^a-z]", "", cand.lower())[:3]):
                out[id_].update(first=cand[:1].upper() + cand[1:], kind="person")
    return out


if __name__ == "__main__":
    import sys
    print(json.dumps(resolve(json.loads(sys.stdin.read())), indent=1))
