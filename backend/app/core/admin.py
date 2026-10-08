"""The operator's admin panel."""
from fastapi import Request
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend

from app import models
from app.db import engine, SessionLocal

from app.core.application import app
from app.core.config import SECRET_KEY
from app.core.security import admin_panel_password, rate_limiter, verify_password


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username, password = form.get("username", ""), form.get("password", "")
        ip = request.client.host if request.client else "unknown"
        if rate_limiter.is_rate_limited(f"admin_panel_login:{ip}", max_requests=5, window=60):
            return False
        if not admin_panel_password():
            return False            # the panel is shut until ADMIN_PASSWORD is set properly
        with SessionLocal() as db:
            user = db.query(models.DBAdminUser).filter_by(username=username).first()
            if user and verify_password(password, user.password):
                request.session.update({"token": "admin_token"})
                return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("token"))


authentication_backend = AdminAuth(secret_key=SECRET_KEY)
admin = Admin(app, engine, authentication_backend=authentication_backend)


class InvoiceAdmin(ModelView, model=models.DBInvoice):
    column_list = [models.DBInvoice.id, models.DBInvoice.number, models.DBInvoice.to_contact, models.DBInvoice.status]


class LineItemAdmin(ModelView, model=models.DBLineItem):
    column_list = [models.DBLineItem.id, models.DBLineItem.invoice_id, models.DBLineItem.description, models.DBLineItem.price]


class SettingsAdmin(ModelView, model=models.DBSettings):
    column_list = [models.DBSettings.id, models.DBSettings.key, models.DBSettings.value]


class ContactAdmin(ModelView, model=models.DBContact):
    column_list = [models.DBContact.id, models.DBContact.name, models.DBContact.email, models.DBContact.phone_number]


class AdminUserAdmin(ModelView, model=models.DBAdminUser):
    column_list = [models.DBAdminUser.id, models.DBAdminUser.username]


admin.add_view(InvoiceAdmin)
admin.add_view(LineItemAdmin)
admin.add_view(SettingsAdmin)
admin.add_view(ContactAdmin)
admin.add_view(AdminUserAdmin)
