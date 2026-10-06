from pathlib import Path

import pytest

from second_brain.config import DEFAULT_REDACTIONS
from second_brain.redaction import Redactor
from second_brain.wiki import check

from conftest import DOCS

LEASE = "leases/apartment-lease.md"


def page(kind: str, body: str, sources: str = f"[{LEASE}]", extra: str = "") -> str:
    return f"---\ntype: {kind}\nsources: {sources}\nupdated: 2026-10-06\n{extra}---\n{body}\n"


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def wiki(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    write(root, "index.md", "# Index\n\n- [[apartment-lease]]\n- [[jordan-reyes]]\n")
    write(root, "log.md", "# Log\n\n## [2026-10-06] ingest | Residential Lease Agreement\n- created [[apartment-lease]]\n")
    write(root, "sources/apartment-lease.md", page(
        "source",
        f"Rent is $1,450/month ({LEASE}). Tenant: [[jordan-reyes]].",
        extra="indexed_at: '2026-10-06T03:36:51.662657+00:00'\n",
    ))
    write(root, "entities/jordan-reyes.md", page(
        "entity", f"Tenant in [[apartment-lease]] ({LEASE}). SSN: [REDACTED_SSN].",
    ))
    return root


def run(wiki: Path, canaries=()):
    return check(wiki, DOCS, Redactor(DEFAULT_REDACTIONS.split(",")), canaries)


def errors(issues):
    return [i for i in issues if i.severity == "error"]


def warnings(issues):
    return [i for i in issues if i.severity == "warning"]


def test_clean_wiki_has_no_issues(wiki):
    assert run(wiki) == []


def test_ssn_is_reported_without_echoing_it(wiki):
    write(wiki, "entities/jordan-reyes.md", page("entity", f"SSN 219-09-9999 ({LEASE}) [[apartment-lease]]"))
    errs = errors(run(wiki))
    assert any("ssn" in e.message for e in errs)
    assert all("219-09-9999" not in e.message for e in run(wiki))


def test_luhn_valid_card_is_an_error(wiki):
    write(wiki, "entities/jordan-reyes.md", page("entity", f"Card 4111 1111 1111 1111 ({LEASE}) [[apartment-lease]]"))
    assert any("credit_card" in e.message for e in errors(run(wiki)))


def test_canary_is_an_error(wiki):
    write(wiki, "entities/jordan-reyes.md", page("entity", f"Code ZEBRA-CANARY ({LEASE}) [[apartment-lease]]"))
    assert any("canary" in e.message for e in errors(run(wiki, canaries=["ZEBRA-CANARY"])))


def test_broken_link_is_an_error(wiki):
    write(wiki, "entities/jordan-reyes.md", page("entity", f"Works at [[acme-analytics]] ({LEASE}) [[apartment-lease]]"))
    assert [e.message for e in errors(run(wiki))] == ["broken link [[acme-analytics]]"]


def test_link_variants_resolve(wiki):
    body = (f"[[jordan-reyes|Jordan]] [[Jordan-Reyes]] [[apartment-lease#Rent]] "
            f"[[entities/jordan-reyes]] [[jordan-reyes.md]] ({LEASE})")
    write(wiki, "topics/people.md", page("topic", body))
    write(wiki, "index.md", "# Index\n\n- [[apartment-lease]]\n- [[jordan-reyes]]\n- [[people]]\n")
    assert errors(run(wiki)) == []


def test_invalid_yaml_is_an_error_not_a_crash(wiki):
    write(wiki, "entities/jordan-reyes.md", f"---\ntype: [unclosed\n---\n[[apartment-lease]] ({LEASE})\n")
    assert any("not valid YAML" in e.message for e in errors(run(wiki)))


def test_missing_frontmatter_is_an_error(wiki):
    write(wiki, "entities/jordan-reyes.md", f"Just text [[apartment-lease]] ({LEASE})\n")
    assert any("missing frontmatter" in e.message for e in errors(run(wiki)))


def test_unknown_type_is_an_error(wiki):
    write(wiki, "entities/jordan-reyes.md", page("person", f"[[apartment-lease]] ({LEASE})"))
    assert any("type must be one of" in e.message for e in errors(run(wiki)))


def test_bad_updated_and_empty_sources_are_errors(wiki):
    write(wiki, "entities/jordan-reyes.md",
          f"---\ntype: entity\nsources: []\nupdated: someday\n---\n[[apartment-lease]] ({LEASE})\n")
    messages = [e.message for e in errors(run(wiki))]
    assert any("sources must be a non-empty list" in m for m in messages)
    assert any("updated must be a date" in m for m in messages)


def test_made_up_sources_are_errors(wiki):
    write(wiki, "entities/jordan-reyes.md",
          page("entity", "[[apartment-lease]] (leases/beach-house.md)", sources="[leases/beach-house.md]"))
    messages = [e.message for e in errors(run(wiki))]
    assert "sources lists unknown document leases/beach-house.md" in messages
    assert "cites unknown document leases/beach-house.md" in messages


def test_markdown_links_are_not_citations(wiki):
    write(wiki, "entities/jordan-reyes.md",
          page("entity", f"See [notes](leases/other.md) and [[apartment-lease]] ({LEASE})"))
    assert errors(run(wiki)) == []


def test_source_page_needs_indexed_at(wiki):
    write(wiki, "sources/apartment-lease.md", page("source", f"[[jordan-reyes]] ({LEASE})"))
    assert any("indexed_at" in e.message for e in errors(run(wiki)))


def test_malformed_log_heading_is_an_error(wiki):
    write(wiki, "log.md", "# Log\n\n## 2026-10-06 ingest Residential Lease\n")
    assert [e.page for e in errors(run(wiki))] == ["log.md"]


def test_duplicate_page_names_are_an_error(wiki):
    write(wiki, "topics/jordan-reyes.md", page("topic", f"[[apartment-lease]] ({LEASE})"))
    assert any("duplicate page name" in e.message for e in errors(run(wiki)))


def test_orphan_is_a_warning_not_an_error(wiki):
    write(wiki, "entities/harbor-view.md", page("entity", f"Landlord ({LEASE}) [[apartment-lease]]"))
    issues = run(wiki)
    assert errors(issues) == []
    assert any(w.page == "entities/harbor-view.md" and "orphan" in w.message for w in warnings(issues))


def test_links_from_index_do_not_rescue_orphans(wiki):
    write(wiki, "entities/harbor-view.md", page("entity", f"Landlord ({LEASE}) [[apartment-lease]]"))
    write(wiki, "index.md", "# Index\n\n- [[apartment-lease]]\n- [[jordan-reyes]]\n- [[harbor-view]]\n")
    assert any("orphan" in w.message for w in warnings(run(wiki)))


def test_page_without_citations_is_a_warning(wiki):
    write(wiki, "entities/jordan-reyes.md", page("entity", "Tenant in [[apartment-lease]]."))
    issues = run(wiki)
    assert errors(issues) == []
    assert any("no inline citations" in w.message for w in warnings(issues))


def test_crlf_and_bom_pages_parse(wiki):
    text = page("entity", f"Tenant in [[apartment-lease]] ({LEASE}).").replace("\n", "\r\n")
    (wiki / "entities" / "jordan-reyes.md").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    assert run(wiki) == []


def test_hidden_folders_are_ignored(wiki):
    write(wiki, ".obsidian/notes.md", "no frontmatter [[nothing]]")
    assert run(wiki) == []


def test_non_utf8_file_is_an_error_not_a_crash(wiki):
    (wiki / "entities" / "latin1.md").write_bytes(b"caf\xe9")
    assert any(e.page == "entities/latin1.md" and "UTF-8" in e.message for e in errors(run(wiki)))


import shutil

from second_brain.wiki import load_pages, parse_page, status


def docs_list(**ingested):
    return [{"source": s, "title": s, "ingested_at": at, "chunks": 1} for s, at in ingested.items()]


def source_page(source: str, indexed_at: str, quoted: bool = True):
    value = f"'{indexed_at}'" if quoted else indexed_at
    return parse_page(f"sources/{Path(source).stem}.md",
                      page("source", f"({source})", sources=f"[{source}]", extra=f"indexed_at: {value}\n"))


AT = "2026-10-06T03:36:51.662657+00:00"
LATER = "2026-10-07T09:00:00.000000+00:00"


def test_status_reports_new_and_changed():
    pages = [source_page(LEASE, AT), source_page("memberships/gym.md", AT)]
    docs = docs_list(**{LEASE: AT, "memberships/gym.md": LATER, "notes/2026-goals.md": AT})
    assert [(d.source, d.state) for d in status(pages, docs)] == [
        ("memberships/gym.md", "changed"),
        ("notes/2026-goals.md", "new"),
    ]


def test_status_accepts_unquoted_timestamps():
    assert status([source_page(LEASE, AT, quoted=False)], docs_list(**{LEASE: AT})) == []


def test_status_ignores_non_source_pages():
    entity = parse_page("entities/x.md", page("entity", f"({LEASE})"))
    assert [d.state for d in status([entity], docs_list(**{LEASE: AT}))] == ["new"]


def test_status_against_a_real_index(brain, tmp_path):
    shutil.copytree(DOCS, brain.settings.docs_dir, dirs_exist_ok=True)
    brain.ingest()
    pages, _ = load_pages(tmp_path / "no-wiki-yet")
    pending = status(pages, brain.list_documents())
    assert len(pending) == 7 and {d.state for d in pending} == {"new"}
