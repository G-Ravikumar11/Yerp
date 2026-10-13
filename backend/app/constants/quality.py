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
    "Flooring": [
        "Sub-base or slab clean, level and free of laitance", "Levels and slope to drains as per the drawing",
        "Bedding or adhesive as specified", "Tiles or finish as approved - batch, shade, size",
        "Joints straight and to the specified width", "No hollow sounds on tapping",
        "Skirting, thresholds and expansion joints", "Cured and protected before use"],
}
# Which kind of work each standard checklist belongs to, for the list.
QC_WORK_TYPES = {
    "Pre-pour (concrete)": "Concrete", "Reinforcement": "Reinforcement", "Shuttering": "Formwork",
    "Brickwork / blockwork": "Brickwork", "Plastering": "Plastering", "Waterproofing": "Waterproofing",
    "Flooring": "Flooring",
}
CUBE_AGES = (7, 28)           # what a set is scheduled for when the project has set no criteria of its own

INSPECTION_RESULTS = ("OPEN", "PASSED", "FAILED")          # shown as Pending, Passed, Failed

NCR_STATUSES = ("OPEN", "ASSIGNED", "UNDER_CORRECTION", "REINSPECTION", "CLOSED")
NCR_LABELS = {"OPEN": "Open", "ASSIGNED": "Assigned", "UNDER_CORRECTION": "Under correction",
              "REINSPECTION": "Reinspection", "CLOSED": "Closed"}
NCR_SEVERITIES = ("Minor", "Major", "Critical")
# An NCR with a root cause required is one that is not a small matter.
NCR_ROOT_CAUSE_FROM = ("Major", "Critical")

# The engineer's decision on a set of cubes.
CUBE_DECISIONS = {"accepted": "Accepted", "conditional": "Accepted with conditions", "rejected": "Rejected"}
CUBE_SPREAD = 0.15            # IS 516: a cube more than 15% off the set's average makes the set doubtful

SERIOUS_KINDS = ("Lost time injury", "Dangerous occurrence", "Fatality")
