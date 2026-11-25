"""Report sections: each PESP step as an `Answer`, written from templates in plain language. No model is involved.

Every function takes the JSON view a tool returns (`profile_to_dict`, `registrations_to_dict`, ... in `watchline.agent.tools`), so the data is already capped and
JSON-safe, the same dicts become the evidence behind each fact, and a section can be rebuilt from saved state. The same view gives the same words, evidence and caveats.

Rules kept in the wording: violations, complaints and cases are what was cited or brought, never findings of fault; counts stay by class, type and status and are never
added into one number; a deed with an amount of 0 is not a sale; only After Inquest or After Trial is a harassment finding, and it is recorded on a case at a building;
a name match is a lead; a person is shown only with the role recorded.
"""
from typing import Any

from watchline.agent.answer import Answer, CaveatOut, Evidence, Fact

MAX_BUILDINGS_SHOWN = 10        # buildings shown in full in a section; the rest are counted and stay in the evidence
MAX_ITEMS_SHOWN = 5             # deeds and cases listed one by one, newest first
MAX_CONTACTS_SHOWN = 12         # contacts listed per registration


def _bbl(d: dict) -> str | None:
    return (d.get("resolution") or {}).get("bbl")


def _ev(section: str, d: dict, data: Any, bin_: str | None = None) -> Evidence:
    return Evidence(section=section, bin=bin_, bbl=_bbl(d), data=data)


def _caveats(*views: dict) -> list[CaveatOut]:
    seen: dict[tuple[str, str], CaveatOut] = {}
    for v in views:
        for c in v.get("caveats") or []:
            seen.setdefault((c["code"], c["text"]), CaveatOut(code=c["code"], text=c["text"]))
    return list(seen.values())


def _sources(*views: dict) -> list[str]:
    return list(dict.fromkeys(s for v in views for s in v.get("sources") or []))


def _say(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def _addr(b: dict) -> str:
    return b.get("address") or "an address not recorded"


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else "none"


def _money(n: int | None) -> str:
    return "no amount recorded" if n is None else f"{n:,}"


def _unavailable(d: dict, what: str) -> Answer | None:
    """The section when the lookup could not be made: say why, from the caveats, and read nothing."""
    if d.get("status") == "error":
        return Answer(kind="error", summary=f"{what} could not be read: the lookup failed. This is an outage, not an answer about the address.",
                      caveats=_caveats(d), sources=_sources(d))
    if d.get("lot") is None:
        why = (d.get("caveats") or [{"text": "the lot is not in the graph"}])[0]["text"]
        return Answer(kind="not_found", summary=f"{what} is not available: {why}", caveats=_caveats(d), sources=_sources(d))
    return None


def _no_buildings(d: dict, what: str) -> Answer | None:
    """A lot with no HPD-registered building has nothing to read: say so, without implying that conditions are fine."""
    if d.get("violations_rate", True) is not None and d.get("case_counts", True) is not None:
        return None
    return Answer(kind="not_found", summary=(f"No {what} can be read: the lot has no HPD-registered building listed. {what[0].upper() + what[1:]} exist only for HPD-registered "
                                             "buildings, so this is not a statement that conditions are good."), caveats=_caveats(d), sources=_sources(d))


# ---- step 5: the owner entity -------------------------------------------------------------------------------------------------

def entity_research(d: dict) -> Answer:
    """The New York DOS records found by name for the registered owner entities and the latest deed's grantees, each a lead."""
    if (a := _unavailable(d, "The owner entity")):
        return a
    subjects = d["subjects"]
    if not subjects:
        return Answer(kind="entities", summary=("There is no entity name to look up: the lot has no corporate registered owner and the latest deed names no entity. "
                                                "Individuals are not looked up."), caveats=_caveats(d), sources=_sources(d))
    facts: list[Fact] = []
    for s in subjects:
        who = f"{s['name']} ({' and '.join(s['roles'])})"
        if not s["records"]:
            facts.append(Fact(statement=(f"{who}: no record in the New York active-entity snapshot under this name (looked up as {s['key']}). That is not a statement that the "
                                         "entity does not exist: dissolved entities, and entities under a different spelling, are absent."), evidence=[_ev("dos_records", d, s)]))
            continue
        for r in s["records"]:
            kind = r["entityType"].title() if r["entityType"] else "entity type not recorded"
            sentence = (f"{who} is a lead for DOS record {r['dosId']}, found by the same name: {kind}" + (f", {r['jurisdiction']}" if r["jurisdiction"] else "")
                        + f", filed {r['filingDate'] or 'on a date not recorded'}. The state forwards legal papers to "
                        + (r["processName"] or "a name not recorded") + (" (the statutory default name, not a person)" if r["defaultProcessName"] else "")
                        + (f" at {r['processAddress']}" if r["processAddress"] else "") + ". Registered agent: "
                        + ((r["agentName"] or "name not recorded") + (f" at {r['agentAddress']}" if r["agentAddress"] else "") if (r["agentName"] or r["agentAddress"]) else "none listed")
                        + ".")
            if (r["processAddressEntities"] or 0) > 1:
                sentence += f" {r['processAddressEntities']:,} entities in the snapshot share this process address."
            facts.append(Fact(statement=sentence, evidence=[_ev("dos_records", d, s)]))
    found = sum(1 for s in subjects if s["records"])
    summary = (f"{_say(len(subjects), 'entity name')} looked up in the New York active-entity snapshot: {found} with a record, {len(subjects) - found} with none. "
               "A match by name is a lead, not proof that the DOS entity is the owner."
               + (f" {_say(d['skipped'], 'grantee')} that look like individuals were not looked up." if d["skipped"] else ""))
    return Answer(kind="entities", summary=summary, facts=facts, caveats=_caveats(d), sources=_sources(d))


def not_covered(title: str, why: str) -> Answer:
    """A step the graph cannot answer yet. It says so and what is missing, so the report never looks silent."""
    return Answer(kind="not_covered", summary=f"Not yet covered: {title}. {why}",
                  caveats=[CaveatOut(code="not_covered", text=f"This report has no section for {title.lower()}. Nothing is implied by its absence.")])


# ---- step 2: the building -----------------------------------------------------------------------------------------------

def building_facts(d: dict) -> Answer:
    """The address, the lot and its buildings, with the lot-wide values kept apart from the buildings."""
    if (a := _unavailable(d, "The building facts")):
        return a
    r, ch = d["resolution"], {c["name"]: c["value"] for c in d["characteristics"]}
    counts = {c["name"]: c["value"] for c in d["counts"]}
    units, hpd, pluto = ch.get("unitsRes"), counts.get("buildings (HPD)"), counts.get("buildings (PLUTO)")
    how = {"exact": "matched exactly", "variant": "matched by a variant spelling"}.get(r["outcome"], f"matched ({r['outcome']})")
    facts = [Fact(statement=f"The address {how} to {r.get('returned') or r['input']}, tax lot {r['bbl']}.", evidence=[_ev("resolution", d, r)]),
             Fact(statement=("PLUTO records the lot as built " + (str(ch["yearBuilt"]) if ch.get("yearBuilt") else "in a year not recorded")
                             + ", building class " + (ch.get("buildingClass") or "not recorded")
                             + f", with {_say(units, 'residential unit') if units is not None else 'no unit count'} and an assessed total of "
                             + (f"${ch['assessedTotal']:,}" if ch.get("assessedTotal") is not None else "not recorded")
                             + ". The units and the assessed total belong to the lot, not to any one building."),
                  evidence=[_ev("characteristics", d, d["characteristics"])]),
             Fact(statement=("HPD registrations list " + _say(hpd or 0, "building") + (", at least that many" if d.get("buildings_listed_is_lower_bound") else "")
                             + "; PLUTO counts " + (f"{pluto:,}" if pluto is not None else "no number of buildings")
                             + ". These are two sources and they can differ."), evidence=[_ev("counts", d, d["counts"])])]
    shown = d["buildings"][:MAX_BUILDINGS_SHOWN]
    if shown:
        listing = "; ".join(f"{_addr(b)} (BIN {b['bin']}){' (the address typed)' if b['addressed'] else ''}" for b in shown)
        more = f" and {(hpd or len(d['buildings'])) - len(shown):,} more" if (hpd or len(d["buildings"])) > len(shown) else ""
        facts.append(Fact(statement=f"The buildings HPD lists for the lot: {listing}{more}.", evidence=[_ev("buildings", d, d["buildings"])]))
    where = r.get("returned") or r["input"]
    summary = (f"{where} is tax lot {r['bbl']}"
               + (f", with {_say(units, 'residential unit')} (a lot-wide figure)" if units is not None else "")
               + f" and {'at least ' if d.get('buildings_listed_is_lower_bound') else ''}{_say(hpd or 0, 'building')} listed by HPD.")
    return Answer(kind="profile", summary=summary, facts=facts, caveats=_caveats(d), sources=_sources(d))


# ---- step 3: the registered owner and the contacts -----------------------------------------------------------------------

def owner_and_contacts(reg: dict, contacts: dict) -> Answer:
    """Who HPD records as the registered owner, and every contact with the role it was recorded in."""
    if (a := _unavailable(reg, "The registered owner")):
        return a
    facts: list[Fact] = []
    contact_by_bin = {b["bin"]: b for b in contacts.get("contact_buildings", [])}
    shown = reg["registration_buildings"][:MAX_BUILDINGS_SHOWN]
    owners_seen: list[str] = []
    for b in shown:
        cb = contact_by_bin.get(b["bin"], {})
        by_reg = {g["registrationId"]: g for g in cb.get("registrations", [])}
        if not b["registrations"]:
            facts.append(Fact(statement=f"{_addr(b)} (BIN {b['bin']}) has no HPD registration in the data. That says nothing about who owns it.",
                              evidence=[_ev("registrations", reg, b, b["bin"])]))
        for g in b["registrations"]:
            owners = [f"{o['name'] or 'a name not recorded'} ({o['contactType']})" for o in g["owners"]]
            owners_seen += [o["name"] for o in g["owners"] if o["name"]]
            dates = (f"last registered {g['lastRegistered']}" if g["lastRegistered"] else "no last-registered date") + (
                f", registration ending {g['registrationEnd']}" if g["registrationEnd"] else "")
            facts.append(Fact(statement=(f"{_addr(b)} (BIN {b['bin']}), registration {g['registrationId']} ({dates}): registered owner as recorded: "
                                         f"{_join(owners) if owners else 'none recorded'}."), evidence=[_ev("registrations", reg, b, b["bin"])]))
            people = by_reg.get(g["registrationId"], {}).get("contacts", [])
            for c in people[:MAX_CONTACTS_SHOWN]:
                where = ", ".join(x for x in (c.get("mailingAddress"), c.get("addressLine2"), c.get("zip")) if x)
                facts.append(Fact(statement=(f"Registration {g['registrationId']} lists {c['name'] or 'a name not recorded'} as {c['role']}"
                                             + (f" (title {c['title']})" if c.get("title") else "") + (f", business address {where}" if where else ", no address recorded") + "."),
                                  evidence=[_ev("contacts", contacts, cb, b["bin"])]))
            if len(people) > MAX_CONTACTS_SHOWN:
                facts.append(Fact(statement=f"{len(people) - MAX_CONTACTS_SHOWN} more contacts are recorded on registration {g['registrationId']}; they are in the evidence.",
                                  evidence=[_ev("contacts", contacts, cb, b["bin"])]))
    if len(reg["registration_buildings"]) > len(shown):
        facts.append(Fact(statement=f"{len(reg['registration_buildings']) - len(shown):,} more buildings are listed; they are in the evidence.",
                          evidence=[_ev("registrations", reg, reg["registration_buildings"])]))
    owners = list(dict.fromkeys(owners_seen))
    summary = (f"HPD records {_join(owners[:3])}{' and others' if len(owners) > 3 else ''} as registered owner. A registration records who registered the building, "
               "not who holds title." if owners else "HPD records no registered owner contact for the buildings on this lot. That says nothing about who owns them.")
    return Answer(kind="registration", summary=summary, facts=facts, caveats=_caveats(reg, contacts), sources=_sources(reg, contacts))


# ---- step 4: deed history -------------------------------------------------------------------------------------------------

def _party(names: list[str], rows: int) -> str:
    shown = _join(names[:3]) if names else "no name recorded"
    return shown + (f" and others ({rows} party rows in all)" if rows > min(len(names), 3) and names else "")


def deed_history(timeline: dict, comparison: dict | None = None) -> Answer:
    """Every recorded deed of the lot, counted as deeds, with the latest compared with the registered owner as a lead."""
    if (a := _unavailable(timeline, "The deed history")):
        return a
    c, deeds = timeline["timeline_counts"], timeline["timeline"]
    if not c["deeds"]:
        return Answer(kind="timeline", summary="No deed is recorded for this lot in the data. That does not mean the lot never changed hands.",
                      caveats=_caveats(timeline), sources=_sources(timeline))
    facts = [Fact(statement=c["plain"], evidence=[_ev("timeline_counts", timeline, c)])]
    for x in deeds[:MAX_ITEMS_SHOWN]:
        if x["amount"] == 0:
            amount = "an amount of 0, which is not a sale"
        elif x["docType"] in ("CORRD", "CONDEED"):
            amount = f"{_money(x['amount'])} (a correction or confirmatory deed, not a sale)"
        elif x["amount"] is None:
            amount = "no amount recorded"
        else:
            amount = f"an amount of {_money(x['amount'])} recorded"
        other = f"; it also names {_say(x['otherLots'], 'other lot')}" if x["otherLots"] else ""
        line = f"Deed {x['documentId']}, recorded {x['recordedDate']} ({x['docType']}), {amount}; from {_party(x['grantors'], x['grantorRows'])} to {_party(x['grantees'], x['granteeRows'])}{other}"
        facts.append(Fact(statement=line if line.endswith(".") else line + ".", evidence=[_ev("timeline", timeline, x)]))      # a name may already end in a period (N.A.)
    if len(deeds) > MAX_ITEMS_SHOWN:
        facts.append(Fact(statement=f"{len(deeds) - MAX_ITEMS_SHOWN:,} older deeds are listed in the evidence.", evidence=[_ev("timeline", timeline, deeds)]))
    if comparison and comparison.get("comparison"):
        facts.append(_latest_deed_against_owner(comparison))
    elif comparison and comparison.get("deeds"):
        facts.append(Fact(statement="The latest deed could not be compared with a registered owner: HPD records none for this lot.", evidence=[_ev("deeds", comparison, comparison["deeds"])]))
    newest = deeds[0]
    summary = (f"{_say(c['deeds'], 'deed')} recorded on the lot, the latest on {newest['recordedDate']}. A deed records a transfer of title, not a sale; "
               f"{c['amountZero']:,} record an amount of 0.")
    return Answer(kind="timeline", summary=summary, facts=facts, caveats=_caveats(timeline, comparison or {}), sources=_sources(timeline, comparison or {}))


def _latest_deed_against_owner(cmp: dict) -> Fact:
    pairs = cmp["comparison"]
    parts = []
    for p in pairs[:MAX_ITEMS_SHOWN]:
        n, a = p["nameAgreement"]["outcome"], p["addressAgreement"]["outcome"]
        name = {"exact_normalized": "are written alike", "normalization_match": "are written alike after normalizing punctuation or case",
                "different": "differ as recorded", "not_comparable": "cannot be compared"}[n]
        addr = {"same": "the addresses are the same", "differs": "the addresses differ", "absent": "an address is missing"}[a]
        parts.append(f"the grantee {p['grantee'] or 'with no name'} and the registered owner {p['owner'] or 'with no name'} {name}, and {addr}")
    return Fact(statement=("Latest deed against the registered owner: " + "; ".join(parts) + ". This compares recorded names and addresses; it is a lead at most, "
                           "never proof that two records are one party."), evidence=[_ev("comparison", cmp, pairs)])


# ---- step 8: conditions ---------------------------------------------------------------------------------------------------

def violations_section(d: dict) -> Answer:
    """Open and closed violations by class, the oldest open inspection and the open count per unit, with the class counts beside it."""
    if (a := _unavailable(d, "The violations")) or (a := _no_buildings(d, "violations")):
        return a
    rate = d["violations_rate"]
    facts: list[Fact] = []
    for b in d["violations"][:MAX_BUILDINGS_SHOWN]:
        if not b["groups"]:
            facts.append(Fact(statement=f"{_addr(b)} (BIN {b['bin']}) has no violation recorded. That is not a statement that conditions are good.",
                              evidence=[_ev("violations", d, b, b["bin"])]))
            continue
        open_ = [f"class {g['violationClass']}: {g['n']}" for g in b["groups"] if g["status"] == "Open"]
        closed = [f"class {g['violationClass']}: {g['n']}" for g in b["groups"] if g["status"] != "Open"]
        facts.append(Fact(statement=(f"{_addr(b)} (BIN {b['bin']}): open violations {_join(open_) if open_ else 'none'}"
                                     + (f"; the oldest open inspection was on {b['oldestOpen']}" if b["oldestOpen"] else "")
                                     + (f"; closed violations {_join(closed)}" if closed else "") + "."), evidence=[_ev("violations", d, b, b["bin"])]))
    if len(d["violations"]) > MAX_BUILDINGS_SHOWN:
        facts.append(Fact(statement=f"{len(d['violations']) - MAX_BUILDINGS_SHOWN:,} more buildings are in the evidence.", evidence=[_ev("violations", d, d["violations"])]))
    if rate["perUnit"] is not None:
        by_class = _join([f"class {c['violationClass']} {c['perUnit']:g}" for c in rate["byClass"]]) if rate["byClass"] else "no open violations in any class"
        text = (f"Open violations per residential unit: {rate['perUnit']:g} ({rate['open']:,} open over {rate['units']:,} units, pooled across the lot's buildings); "
                f"by class: {by_class}. The units are a lot-wide figure.")
    else:
        text = f"The rate per unit is unavailable (the lot has no residential unit count, or the building list was cut). Open violations counted: {rate['open']:,}."
    facts.append(Fact(statement=text, evidence=[_ev("violations_rate", d, rate)]))
    summary = (f"{_say(rate['open'], 'open violation')} on the lot's buildings. Violations are what an inspector cited, not findings of fault or a measure of how bad conditions are."
               if rate["open"] else "No open violation is recorded for the lot's buildings. That is not a statement that conditions are good.")
    return Answer(kind="violations", summary=summary, facts=facts, caveats=_caveats(d), sources=_sources(d))


def litigation_section(d: dict) -> Answer:
    """Housing Court cases brought against the lot's buildings, any recorded harassment finding, and how each respondent compares with the owner names."""
    if (a := _unavailable(d, "The litigation")) or (a := _no_buildings(d, "Housing Court cases")):
        return a
    c = d["case_counts"]
    if not c["cases"]:
        return Answer(kind="litigation", summary="No Housing Court case is recorded for the lot's buildings. That does not mean none was ever brought.",
                      caveats=_caveats(d), sources=_sources(d))
    kv = lambda m: _join([f"{k}: {v:,}" for k, v in m.items()])    # noqa: E731
    facts = [Fact(statement=f"Cases by type: {kv(c['byType'])}. By status: {kv(c['byStatus'])}. By harassment finding: {kv(c['byFinding'])}.",
                  evidence=[_ev("case_counts", d, c)])]
    findings = [x for x in d["cases"] if x["isHarassmentFinding"]]
    for x in findings:
        facts.append(Fact(statement=(f"Case {x['litigationId']} ({x['caseType']}, opened {x['caseOpenDate'] or 'on a date not recorded'}, {x['caseStatus']}) has a recorded "
                                     f"harassment finding, {x['harassmentFinding']}, dated {x['findingDate'] or 'not recorded'}"
                                     + (f", with a penalty of {x['penalty']:,}" if x["penalty"] is not None else "") + f". The finding is recorded on this case at the building. "
                                     f"{_respondent(x)}"), evidence=[_ev("cases", d, x)]))
    for x in [x for x in d["cases"] if not x["isHarassmentFinding"]][:MAX_ITEMS_SHOWN]:
        facts.append(Fact(statement=(f"Case {x['litigationId']} ({x['caseType']}, opened {x['caseOpenDate'] or 'on a date not recorded'}, {x['caseStatus']}); "
                                     f"no harassment finding recorded. {_respondent(x)}"), evidence=[_ev("cases", d, x)]))
    if c["cases"] > len(d["cases"]):
        facts.append(Fact(statement=f"{c['cases'] - len(d['cases']):,} more cases are counted above and not listed.", evidence=[_ev("case_counts", d, c)]))
    summary = (f"HPD recorded {_say(c['cases'], 'Housing Court case')} on the lot's buildings, brought by the city, not findings of fault. "
               + (f"{_say(len(findings), 'case')} {'carries' if len(findings) == 1 else 'carry'} a recorded harassment finding (After Inquest or After Trial)." if findings
                  else "No harassment finding (After Inquest or After Trial) is recorded."))
    return Answer(kind="litigation", summary=summary, facts=facts, caveats=_caveats(d), sources=_sources(d))


def _respondent(x: dict) -> str:
    who = x["respondent"] or "none recorded"
    if x["respondentMatch"] == "lead":
        parts = _join([m["part"] for m in x["matches"]])
        return f"Respondent as recorded: {who}. {parts} matches a registered owner name as written; that is a lead, not proof of the same party."
    if x["respondentMatch"] == "none":
        return f"Respondent as recorded: {who}. No part of it matches a registered owner name."
    return f"Respondent as recorded: {who}. It cannot be compared with an owner name."
