"""The fixed lists, limits and statuses for quality."""



# QUALITY: CHECKLISTS, CUBE TESTS AND NON-CONFORMANCES
#
# What is poured over cannot be looked at again. The checklist is walked
# before it is covered - reinforcement, shuttering, the pre-pour - item by
# item; the cubes cast from each pour are crushed at seven and twenty-eight
# days and read against the grade; and anything not as specified becomes a
# non-conformance with an owner and a date, open until somebody closes it
# with what was done.
QC_CHECKLISTS = {
    "Pre-pour (concrete)": [
        "Reinforcement as per the drawing - diameter, spacing, laps",
        "Cover blocks in place, correct cover", "Shuttering in line, level and plumb, joints tight",
        "Shuttering clean and oiled", "Sleeves, inserts and embedments fixed",
        "Construction joint prepared", "Grade and slump confirmed on the docket",
        "Vibrators working, a standby on site", "Curing arranged", "Client's engineer has cleared the pour"],
    "Reinforcement": [
        "Bar diameter and grade (Fe500D) as per the BBS", "Number and spacing of bars",
        "Lap lengths and where the laps fall", "Bends, hooks and anchorage",
        "Chairs and spacers", "Tied with binding wire, no loose bars", "Clear cover",
        "Bars clean - no rust flakes, oil or mud"],
    "Shuttering": [
        "Plates and ply in good condition", "Dimensions as per the drawing", "Line, level and plumb",
        "Props and staging adequate and braced", "Joints sealed against leakage",
        "Release agent applied", "Openings and cut-outs in the right place"],
    "Brickwork / blockwork": [
        "Bricks soaked before laying", "Mortar mix as specified", "Courses in line and level",
        "Plumb", "Joints full and not over 10 mm", "Bond as specified", "Curing"],
    "Plastering": [
        "Surface hacked, cleaned and wetted", "Mix as specified", "Thickness", "Line and level",
        "Corners and edges true", "Curing"],
    "Waterproofing": [
        "Surface clean and dry", "Primer applied", "Membrane or coating as specified",
        "Laps and upstands", "Flood test held (24/48 h)", "Protection screed laid"],
}
CUBE_AGES = (7, 28)
EARLY_SHARE = 0.65            # a 7-day set is expected near two-thirds of the grade

SERIOUS_KINDS = ("Lost time injury", "Dangerous occurrence", "Fatality")
