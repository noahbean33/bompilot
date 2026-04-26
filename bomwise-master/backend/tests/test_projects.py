import hashlib
import io
import os
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.models.password_reset_token import PasswordResetToken

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
PROJECTS_URL = "/projects/"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client: TestClient, db_session, email: str, password: str = "password123") -> str:
    """Register a user (no password), create a reset token, set password, and login."""
    register_resp = client.post(REGISTER_URL, json={"email": email, "name": "Test User"})
    user_id = register_resp.json()["id"]

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    db_session.add(PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    db_session.commit()

    client.post("/auth/reset-password", json={"token": raw_token, "new_password": password})

    resp = client.post(LOGIN_URL, json={"email": email, "password": password})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_project(client: TestClient, token: str, name: str = "My Project") -> dict:
    resp = client.post(PROJECTS_URL, json={"name": name}, headers=_auth(token))
    assert resp.status_code == 201
    return resp.json()


_SAMPLE_CSV = """\
Reference,Value,Footprint,Description,Quantity,MPN
C1,100nF,C_0402,Decoupling cap,10,GRM155R61A104KA01D
R1,10k,R_0402,Pull-up resistor,5,RC0402FR-0710KL
U1,STM32F103,LQFP48,MCU,1,STM32F103C8T6
"""


def _csv_file(csv_text: str = _SAMPLE_CSV):
    return {"file": ("bom.csv", io.BytesIO(csv_text.encode()), "text/csv")}


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


def test_create_project(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    resp = client.post(
        PROJECTS_URL,
        json={"name": "Widget Rev A", "description": "Main PCB", "variant_tag": "rev-a"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Widget Rev A"
    assert data["description"] == "Main PCB"
    assert data["variant_tag"] == "rev-a"
    assert "id" in data
    assert "user_id" in data


def test_create_project_requires_auth(client: TestClient):
    resp = client.post(PROJECTS_URL, json={"name": "No auth"})
    assert resp.status_code == 401


def test_list_projects_empty(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    resp = client.get(PROJECTS_URL, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_projects(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    _create_project(client, token, "Project A")
    _create_project(client, token, "Project B")

    resp = client.get(PROJECTS_URL, headers=_auth(token))
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert names == {"Project A", "Project B"}


def test_list_projects_scoped_to_user(client: TestClient, db_session):
    token_a = _register_and_login(client, db_session, "alice@example.com")
    token_b = _register_and_login(client, db_session, "bob@example.com")
    _create_project(client, token_a, "Alice's project")
    _create_project(client, token_b, "Bob's project")

    alice_projects = client.get(PROJECTS_URL, headers=_auth(token_a)).json()
    assert len(alice_projects) == 1
    assert alice_projects[0]["name"] == "Alice's project"


def test_get_project(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    resp = client.get(f"{PROJECTS_URL}{project['id']}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == project["id"]


def test_get_project_not_found(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    resp = client.get(f"{PROJECTS_URL}9999", headers=_auth(token))
    assert resp.status_code == 404


def test_get_project_wrong_user(client: TestClient, db_session):
    token_a = _register_and_login(client, db_session, "alice@example.com")
    token_b = _register_and_login(client, db_session, "bob@example.com")

    project = _create_project(client, token_a)
    resp = client.get(f"{PROJECTS_URL}{project['id']}", headers=_auth(token_b))
    assert resp.status_code == 404


def test_delete_project(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    resp = client.delete(f"{PROJECTS_URL}{project['id']}", headers=_auth(token))
    assert resp.status_code == 204

    resp = client.get(f"{PROJECTS_URL}{project['id']}", headers=_auth(token))
    assert resp.status_code == 404


def test_delete_project_wrong_user(client: TestClient, db_session):
    token_a = _register_and_login(client, db_session, "alice@example.com")
    token_b = _register_and_login(client, db_session, "bob@example.com")

    project = _create_project(client, token_a)
    resp = client.delete(f"{PROJECTS_URL}{project['id']}", headers=_auth(token_b))
    assert resp.status_code == 404

    # Project still exists for owner
    resp = client.get(f"{PROJECTS_URL}{project['id']}", headers=_auth(token_a))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# BOM CSV import
# ---------------------------------------------------------------------------


def test_import_bom(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == project["id"]
    assert data["imported"] == 3


def test_import_bom_lines_content(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(),
        headers=_auth(token),
    )
    lines = client.get(
        f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)
    ).json()

    assert len(lines) == 3
    refs = {line["reference"] for line in lines}
    assert refs == {"C1", "R1", "U1"}

    c1 = next(l for l in lines if l["reference"] == "C1")
    assert c1["value"] == "100nF"
    assert c1["quantity"] == 10
    assert c1["mpn_raw"] == "GRM155R61A104KA01D"
    assert "Reference" in c1["raw_fields"]  # full original row stored


def test_import_bom_merges_new_ref_and_retains_existing(client: TestClient, db_session):
    """Re-import with a new REF adds it; existing REFs absent from new CSV are retained (UIF-014)."""
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)
    pid = project["id"]

    # First import: C1, R1, U1
    client.post(f"{PROJECTS_URL}{pid}/bom/import", files=_csv_file(), headers=_auth(token))

    # Second import: only D1 — C1, R1, U1 are absent from this CSV
    second_csv = "Reference,Value,Quantity\nD1,LED,2\n"
    resp = client.post(
        f"{PROJECTS_URL}{pid}/bom/import",
        files=_csv_file(second_csv),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 1  # one row in the CSV
    assert len(data["warnings"]) == 3  # C1, R1, U1 warned

    lines = client.get(f"{PROJECTS_URL}{pid}/bom", headers=_auth(token)).json()
    # All 4 REFs should be present: D1 was added, C1/R1/U1 were retained
    assert len(lines) == 4
    refs = {ln["reference"] for ln in lines}
    assert "D1" in refs
    assert "C1" in refs
    assert "R1" in refs
    assert "U1" in refs


def test_import_bom_identical_ref_retains_match_state(client: TestClient, db_session):
    """Re-import with identical Value+Footprint retains existing match data (UIF-014)."""
    token = _register_and_login(client, db_session, "alice2@example.com")
    project = _create_project(client, token)
    pid = project["id"]

    # Import C1 with a known value + footprint
    first_csv = "Reference,Value,Footprint,Quantity\nC1,100nF,C_0402,10\n"
    client.post(
        f"{PROJECTS_URL}{pid}/bom/import",
        files=_csv_file(first_csv),
        headers=_auth(token),
    )
    lines = client.get(f"{PROJECTS_URL}{pid}/bom", headers=_auth(token)).json()
    c1_id_before = next(l for l in lines if l["reference"] == "C1")["id"]

    # Re-import with same value+footprint — should retain the row (same DB id)
    second_csv = "Reference,Value,Footprint,Quantity\nC1,100nF,C_0402,20\n"
    resp = client.post(
        f"{PROJECTS_URL}{pid}/bom/import",
        files=_csv_file(second_csv),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["warnings"] == []

    lines2 = client.get(f"{PROJECTS_URL}{pid}/bom", headers=_auth(token)).json()
    c1_after = next(l for l in lines2 if l["reference"] == "C1")
    assert c1_after["id"] == c1_id_before  # same row retained
    assert c1_after["quantity"] == 20  # quantity updated


def test_import_bom_changed_value_clears_match_state(client: TestClient, db_session):
    """Re-import with changed Value clears match_type and selected_result_id (UIF-014)."""
    token = _register_and_login(client, db_session, "alice3@example.com")
    project = _create_project(client, token)
    pid = project["id"]

    first_csv = "Reference,Value,Footprint,Quantity\nC1,100nF,C_0402,10\n"
    client.post(
        f"{PROJECTS_URL}{pid}/bom/import",
        files=_csv_file(first_csv),
        headers=_auth(token),
    )

    # Re-import with different value — match_type should be cleared
    second_csv = "Reference,Value,Footprint,Quantity\nC1,220nF,C_0402,10\n"
    resp = client.post(
        f"{PROJECTS_URL}{pid}/bom/import",
        files=_csv_file(second_csv),
        headers=_auth(token),
    )
    assert resp.status_code == 200

    lines = client.get(f"{PROJECTS_URL}{pid}/bom", headers=_auth(token)).json()
    c1 = next(l for l in lines if l["reference"] == "C1")
    assert c1["value"] == "220nF"
    assert c1["match_type"] is None  # cleared for re-matching
    assert c1["selected_result"] is None


def test_import_bom_wrong_user(client: TestClient, db_session):
    token_a = _register_and_login(client, db_session, "alice@example.com")
    token_b = _register_and_login(client, db_session, "bob@example.com")

    project = _create_project(client, token_a)
    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(),
        headers=_auth(token_b),
    )
    assert resp.status_code == 404


def test_import_bom_empty_csv(client: TestClient, db_session):
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(""),
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_import_bom_raw_fields_complete(client: TestClient, db_session):
    """Every column from the CSV row must appear in raw_fields."""
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    csv_text = "Reference,Value,Footprint,Description,Quantity,MPN,CustomCol\nR5,4k7,R_0603,Resistor,3,RC0603FR-074K7L,extra\n"
    client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(csv_text),
        headers=_auth(token),
    )
    lines = client.get(f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)).json()
    assert lines[0]["raw_fields"]["CustomCol"] == "extra"


# ---------------------------------------------------------------------------
# KiCad Symbol Fields Table compatibility (BOM-13)
# ---------------------------------------------------------------------------


def test_import_bom_refs_alias(client: TestClient, db_session):
    """'Refs' column (plural) is normalised to reference."""
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    csv_text = "Refs,Value,Qty\n\"R1,R2\",10k,2\nU1,STM32,1\n"
    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(csv_text),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 2

    lines = client.get(f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)).json()
    refs = {ln["reference"] for ln in lines}
    assert "R1,R2" in refs
    assert "U1" in refs


def test_import_bom_qty_alias(client: TestClient, db_session):
    """'Qty' column is normalised to quantity."""
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    csv_text = "Reference,Value,Qty\nC1,100nF,5\n"
    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(csv_text),
        headers=_auth(token),
    )
    assert resp.status_code == 200

    lines = client.get(f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)).json()
    assert lines[0]["quantity"] == 5


def test_import_bom_mpn_optional(client: TestClient, db_session):
    """CSV with no MPN column imports cleanly; mpn_raw is null on all rows."""
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    csv_text = "Reference,Value,Footprint,Qty\nC1,100nF,C_0402,10\nR1,10k,R_0402,4\n"
    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(csv_text),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 2

    lines = client.get(f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)).json()
    assert all(ln["mpn_raw"] is None for ln in lines)


def test_import_bom_dnp_column(client: TestClient, db_session):
    """DNP column: non-empty value → dnp=True; empty value → dnp=False."""
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    csv_text = (
        "Reference,Value,Qty,DNP\n"
        "R1,10k,1,x\n"       # DNP
        "C1,100nF,2,\n"      # not DNP (empty cell)
        "U1,MCU,1,1\n"       # DNP (non-empty)
    )
    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(csv_text),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 3

    lines = client.get(f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)).json()
    by_ref = {ln["reference"]: ln for ln in lines}
    assert by_ref["R1"]["dnp"] is True
    assert by_ref["C1"]["dnp"] is False
    assert by_ref["U1"]["dnp"] is True


def test_import_bom_exclude_from_bom_column(client: TestClient, db_session):
    """'Exclude from BOM' column sets dnp=True when non-empty."""
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    csv_text = (
        "Reference,Value,Qty,Exclude from BOM\n"
        "J1,Connector,1,x\n"   # excluded
        "R1,10k,4,\n"           # not excluded
    )
    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(csv_text),
        headers=_auth(token),
    )
    assert resp.status_code == 200

    lines = client.get(f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)).json()
    by_ref = {ln["reference"]: ln for ln in lines}
    assert by_ref["J1"]["dnp"] is True
    assert by_ref["R1"]["dnp"] is False


def test_import_bom_grouped_references(client: TestClient, db_session):
    """Comma-separated reference groups (KiCad BOM rows) import as single lines."""
    token = _register_and_login(client, db_session, "alice@example.com")
    project = _create_project(client, token)

    csv_text = (
        "Refs,Value,Footprint,Qty\n"
        "\"C1,C2,C3\",100nF,C_0402,3\n"
        "\"R1,R2\",10k,R_0402,2\n"
        "U1,MCU,LQFP-64,1\n"
    )
    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files=_csv_file(csv_text),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 3

    lines = client.get(f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)).json()
    assert len(lines) == 3
    refs = {ln["reference"] for ln in lines}
    assert "C1,C2,C3" in refs
    assert "R1,R2" in refs
    assert "U1" in refs


def test_import_bom_kicad_fixture_52_rows(client: TestClient, db_session):
    """Full KiCad Symbol Fields Table fixture: 52 rows, 5 DNP, no MPN column."""
    from app.models.user import User

    token = _register_and_login(client, db_session, "alice@example.com")
    # Upgrade to paid plan so the 52-row fixture clears the free-tier 50-part cap
    db_session.query(User).filter(User.email == "alice@example.com").update({"plan": "paid"})
    db_session.commit()

    project = _create_project(client, token)

    fixture_path = os.path.join(_FIXTURES_DIR, "kicad_symbol_fields.csv")
    with open(fixture_path, "rb") as f:
        csv_bytes = f.read()

    resp = client.post(
        f"{PROJECTS_URL}{project['id']}/bom/import",
        files={"file": ("kicad_symbol_fields.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["imported"] == 52
    assert data["warnings"] == []

    lines = client.get(f"{PROJECTS_URL}{project['id']}/bom", headers=_auth(token)).json()
    assert len(lines) == 52

    # No MPN column → all mpn_raw should be null
    assert all(ln["mpn_raw"] is None for ln in lines)

    # 5 DNP rows: D5, J4, R17 (DNP col), R18 (Exclude from BOM col), U10
    dnp_refs = {ln["reference"] for ln in lines if ln["dnp"]}
    assert "D5" in dnp_refs
    assert "J4" in dnp_refs
    assert "R17" in dnp_refs
    assert "R18" in dnp_refs
    assert "U10" in dnp_refs
    assert len(dnp_refs) == 5

    # Refs column maps correctly (grouped references intact)
    all_refs = {ln["reference"] for ln in lines}
    assert "C1,C2,C3,C4,C5,C6,C7,C8" in all_refs
    assert "R1,R2,R3,R4,R5,R6,R7,R8" in all_refs
    assert "Z1,Z2" in all_refs
