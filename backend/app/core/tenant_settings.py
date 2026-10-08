"""Company-wide settings kept in the database."""
from app import models


def tenant_setting(db, client_id, key, default=""):
    row = db.query(models.DBSettings).filter(
        models.DBSettings.client_id == client_id, models.DBSettings.key == key
    ).first()
    return (row.value if row and row.value not in (None, "") else default)


#
# What prints on a work order is only as good as what is on file. The company
# block, the gang's PAN and GSTIN, the conditions and the signatures could be
# entered once and never corrected; these routes let them be kept up.
def put_setting(db, client_id, key, value):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id,
                                             models.DBSettings.key == key).first()
    if row:
        row.value = value
    else:
        db.add(models.DBSettings(client_id=client_id, key=key, value=value))
