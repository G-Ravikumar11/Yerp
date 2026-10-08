"""The fixed lists, limits and statuses for assets."""



# EQUIPMENT AND ASSETS
#
# What the business owns and what it hires in, where each machine is, what it
# did and burned each day, and when it is next due - so a service is not found
# to be overdue by a breakdown on the day of the pour. Every rupee a machine
# costs - diesel, hire, repairs - lands on the project it was working for.
ASSET_CATEGORIES = ("Earthmoving", "Concrete", "Lifting", "Transport", "Compaction",
                    "Power", "Pumping", "Shuttering", "Survey", "Tools", "Vehicle",
                    "Computers", "Furniture", "Office equipment", "Building", "Other")

HIRE_BASES = ("Hour", "Day", "Month")
# The working days a monthly hire is spread across, the way sites cost it.
DAYS_IN_A_HIRE_MONTH = 26

# FIXED ASSETS AND DEPRECIATION
#
# The equipment register says where a machine is and what it burned. It did
# not say what it is worth: an excavator bought for forty lakhs three years
# ago was carried at forty lakhs for ever, and the depreciation schedule the
# auditor asks for every March was built by hand from the purchase bills.
#
# Two books, because the law keeps two. The company's own (Schedule II:
# straight line or written-down value over a useful life, pro rata from the
# day the asset was put to use) and the income-tax one (blocks of assets at
# a rate, half the rate on anything used for less than 180 days in the year
# it was bought). The lives and rates below are the usual ones and are only
# where each asset starts - every one of them can be changed.
# Category -> (useful life in years, income-tax block).
ASSET_BOOK_DEFAULTS = {
    "Earthmoving": (9, "Plant & machinery"),
    "Concrete": (12, "Plant & machinery"),
    "Lifting": (15, "Plant & machinery"),
    "Compaction": (12, "Plant & machinery"),
    "Transport": (8, "Motor vehicles"),
    "Vehicle": (8, "Motor vehicles"),
    "Power": (15, "Plant & machinery"),
    "Pumping": (15, "Plant & machinery"),
    "Shuttering": (12, "Plant & machinery"),
    "Survey": (15, "Plant & machinery"),
    "Tools": (15, "Plant & machinery"),
    "Computers": (3, "Computers"),
    "Furniture": (10, "Furniture & fittings"),
    "Office equipment": (5, "Plant & machinery"),
    "Building": (60, "Buildings"),
    "Other": (15, "Plant & machinery"),
}
TAX_BLOCK_DEFAULTS = (("Plant & machinery", 15.0), ("Motor vehicles", 15.0),
                      ("Lorries used on hire", 30.0), ("Computers", 40.0),
                      ("Furniture & fittings", 10.0), ("Buildings", 10.0),
                      ("Intangible assets", 25.0))
BOOK_METHODS = ("WDV", "SLM")
HALF_RATE_DAYS = 180
