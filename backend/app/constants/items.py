"""The fixed lists, limits and statuses for items."""



ITEM_COLUMNS = ["item_code", "item_name", "segment", "description", "category",
                "sub_category", "hsn_code", "item_tax_type", "item_type",
                "units_of_measure", "make"]
ITEM_HEADERS = ["Item Code", "Item Name", "Segment", "Description", "Category",
                "Sub Category", "HSN Code", "Item Tax Type", "Item Type",
                "Units Of Measure", "Make"]

BOM_COLUMNS = ["fg_code", "rm_code", "rm_name", "qty", "uom", "rate"]
BOM_HEADERS = ["FG Code", "RM Code", "RM Name", "Qty", "UOM", "Rate"]

ITEM_TYPE_ALIASES = {
    "Purchased": ["purchased", "purchase", "buy", "bought", "supply", "material", "goods"],
    "Service": ["service", "services", "labour", "labor", "work", "installation"],
}
