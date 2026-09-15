"""A rupee figure the way it is read aloud here.

Indian grouping puts the first comma three from the right and every one after
it two apart: twelve lakh is 12,00,000, not 1,200,000. The server had no
formatter, so every figure it wrote into a sentence came out as a bare float -
"400000.0 the customer should already have paid" - which is the kind of thing
that makes a whole screen look unfinished at a glance.
"""
from main import inr


def test_small_numbers_have_no_grouping():
    assert inr(0) == "₹0.00"
    assert inr(310) == "₹310.00"
    assert inr(999) == "₹999.00"


def test_the_first_comma_sits_three_from_the_right():
    assert inr(1000) == "₹1,000.00"
    assert inr(99999) == "₹99,999.00"


def test_a_lakh_groups_in_twos_after_that():
    assert inr(100000) == "₹1,00,000.00"
    assert inr(400000) == "₹4,00,000.00"
    assert inr(125140) == "₹1,25,140.00"


def test_a_crore_keeps_going_in_twos():
    assert inr(10000000) == "₹1,00,00,000.00"
    assert inr(2345678.9) == "₹23,45,678.90"
    assert inr(470000001) == "₹47,00,00,001.00"


def test_paise_are_kept_and_rounded():
    assert inr(4650.5) == "₹4,650.50"
    assert inr(12.345) == "₹12.35"


def test_a_negative_figure_keeps_its_sign_outside_the_symbol():
    assert inr(-1200) == "-₹1,200.00"


def test_it_survives_junk():
    assert inr(None) == "₹0.00"
    assert inr("") == "₹0.00"
