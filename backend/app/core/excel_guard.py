"""Text that looks like a formula is stored as text, never run, in every workbook the app writes."""
import openpyxl.cell.cell as _xl_cell


_bind_cell_value = _xl_cell.Cell._bind_value


def _bind_text_not_formula(self, value):
    _bind_cell_value(self, value)
    if self.data_type == "f":
        self.data_type = "s"


_xl_cell.Cell._bind_value = _bind_text_not_formula
