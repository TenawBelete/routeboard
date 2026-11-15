import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from names import parse_line  # noqa: E402


def test_well_known_networks_get_the_name_people_use():
    assert parse_line("15169 GOOGLE, US") == (15169, "GOOGLE", "Google", "US")
    assert parse_line("3356 LEVEL3, US")[2] == "Lumen"


def test_description_is_preferred_over_handle():
    assert parse_line("7552 VIETEL-AS-AP Viettel Group, VN") == (7552, "VIETEL-AS-AP", "Viettel Group", "VN")
    assert parse_line("9583 SIFY-AS-IN Sify Limited, IN")[2] == "Sify"
    assert parse_line("64496 EXAMPLE-NET Example Networks, Inc., US")[2] == "Example Networks"


def test_handle_only_is_cleaned_up():
    assert parse_line("400644 BGPKIT-LLC, US")[2] == "BGPKIT LLC".title()
    assert parse_line("64497 ACME-AS, DE")[2] == "ACME"


def test_malformed_lines_are_skipped_not_fatal():
    for bad in ["", "garbage", "abc NAME, US", "23456 -Reserved AS-, ZZ"]:
        assert parse_line(bad) is None
    assert parse_line("64498 NOCOUNTRY Some Org")[3] is None      # country missing -> None, row kept
    assert parse_line("64499 ODD Some Org, EUROPE")[3] is None


def test_dash_separated_forms_seen_in_the_real_file():
    assert parse_line("6147 - Integratel Peru S.A.A., PE")[2] == "Integratel Peru"
    assert parse_line("396982 GOOGLE-CLOUD-PLATFORM - Google LLC, US")[1:3] == ("GOOGLE-CLOUD-PLATFORM", "Google")
    assert parse_line("32381 CLOUD NETWORKING - Google Access, US")[1:3] == ("CLOUD-NETWORKING", "Google Access")
    assert parse_line("64501 - Alojalia Cloud S.L., ES")[2] == "Alojalia Cloud"


def test_more_company_endings_and_parenthesised_tails():
    assert parse_line("11172 - Alestra, S. de R.L. de C.V., MX")[2] == "Alestra"
    assert parse_line("5617 TPNET - Orange Polska Spolka Akcyjna, PL")[2] == "Orange Polska"
    assert parse_line("9009 M247 - M247 Europe SRL, RO")[2] == "M247 Europe"
    assert parse_line("15706 - Sudatel (Sudan Telecom Co. Ltd), SD")[2] == "Sudatel"
    assert parse_line("721 - United States Department of Defense (DoD), US")[2] == "United States Department of Defense"
    assert parse_line("30987 - Eritrea Telecommunication Service corporation (EriTel), ER")[2] == "EriTel"
