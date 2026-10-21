"""Spelling/transliteration variants of the same event generate the same searches."""
from agents.query_variants import canonical_spelling, expand_queries, gdelt_query, variant_queries

NIMARJAN = "Schools in Hyderabad were closed on a single day because of Ganesh Nimarjan"
NIMAJJANAM = "Schools in Hyderabad were closed on a single day because of Ganesh Nimajjanam"


def test_two_spellings_produce_the_same_query_variants():
    assert variant_queries(NIMARJAN, limit=10) == variant_queries(NIMAJJANAM, limit=10)
    assert expand_queries([NIMARJAN], NIMARJAN) == expand_queries([NIMAJJANAM], NIMAJJANAM)
    assert gdelt_query(NIMARJAN) == gdelt_query(NIMAJJANAM)


def test_variants_still_search_every_spelling():
    joined = " ".join(variant_queries(NIMARJAN, limit=10)).lower()
    for spelling in ("nimajjanam", "nimarjan", "visarjan"):
        assert spelling in joined


def test_rare_spellings_are_aliases_of_the_same_event():
    a = "Ganesh Nimajanam holiday in Hyderabad"
    b = "Ganesh Nimarjanam holiday in Hyderabad"
    assert canonical_spelling(a) == canonical_spelling(b) == "Ganesh immersion holiday in Hyderabad"


def test_canonical_spelling_leaves_synonyms_and_other_text_alone():
    assert canonical_spelling("Ganesh Nimarjan holiday") == "Ganesh immersion holiday"
    assert canonical_spelling("Schools closed in Hyderabad") == "Schools closed in Hyderabad"
