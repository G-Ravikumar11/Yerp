"""Builds the application.

The order below is the order it has to happen in:
  1. config - reads .env, sets the time zone and logging. Nothing may read the environment before it.
  2. the Excel guard - text that looks like a formula is never run.
  3. the application object, the admin panel, sign-in with Google, then the layers that wrap every request.
  4. every router, in the order their routes are matched.
  5. the front end last: it is mounted on "/", which would otherwise answer everything.
"""
# ruff: noqa: F401
from app.core import config
from app.core import excel_guard
from app.core.application import app
from app.core import oauth, admin, middleware, errors

# Everything the routers and the scheduler draw on, loaded explicitly so nothing depends on who asks first.
from app.constants import (
    approvals,
    assets,
    boq,
    client_billing,
    compliance,
    common,
    crm,
    hr,
    invoicing,
    items,
    money,
    projects,
    quality,
    recruitment,
    settings,
    subcontract_orders,
    wallet_ai,
)
from app.core import (
    audit,
    auth,
    cache,
    currency,
    dates,
    files,
    gst,
    lifecycle,
    notifications,
    permissions,
    queries,
    scheduler,
    security,
    serials,
    sheets,
    tenant_settings,
    units,
)
from app.documents import (
    forms,
    letterhead,
    pdf_twins,
)
from app.schemas import (
    access,
    approvals,
    assets,
    auth,
    boq,
    client_billing,
    compliance,
    client_orders,
    collaboration,
    crm,
    drawings,
    employee_portal,
    hr,
    invoicing,
    items,
    money,
    partner_portal,
    payroll,
    procurement,
    projects,
    quality,
    recruitment,
    safety,
    settings,
    stores,
    subcontract_billing,
    subcontract_orders,
    superadmin,
    wallet_ai,
)
from app.services import (
    access,
    approvals,
    assets,
    auth,
    boq,
    client_billing,
    compliance,
    client_orders,
    collaboration,
    crm,
    email,
    employee_portal,
    files,
    hr,
    invoicing,
    items,
    money,
    partner_portal,
    payroll,
    procurement,
    projects,
    quality,
    recruitment,
    safety,
    settings,
    stores,
    subcontract_billing,
    subcontract_orders,
    wallet_ai,
)
from app.validators import (
    common,
    hr,
)

from app.routers import (
    auth,
    superadmin,
    projects,
    invoicing,
    email,
    crm,
    items,
    files,
    client_orders,
    approvals,
    money,
    system,
    settings,
    employee_portal,
    recruitment,
    access,
    hr,
    payroll,
    attendance,
    procurement,
    public,
    wallet_ai,
    collaboration,
    subcontract_orders,
    boq,
    subcontract_billing,
    client_billing,
    stores,
    assets,
    drawings,
    quality,
    safety,
    partner_portal,
    compliance,
    master_delete,
)

for _module in (
    auth,
    superadmin,
    projects,
    invoicing,
    email,
    crm,
    items,
    files,
    client_orders,
    approvals,
    money,
    system,
    settings,
    employee_portal,
    recruitment,
    access,
    hr,
    payroll,
    attendance,
    procurement,
    public,
    wallet_ai,
    collaboration,
    subcontract_orders,
    boq,
    compliance,
    subcontract_billing,
    client_billing,
    stores,
    assets,
    drawings,
    quality,
    safety,
    partner_portal,
    master_delete,
):
    app.include_router(_module.router)

# Everything that calls an AI model lives in the Ai_service folder, one file per function.
from Ai_service import routers as ai_routers
for _router in ai_routers:
    app.include_router(_router)

# A .pdf beside every .xlsx - now that every route is in place.
from app.documents.pdf_twins import add_pdf_twins
PDF_TWINS = add_pdf_twins()

from app.core import static
