"""The item master endpoints for BOQ work items: list, edit, status, categories, and where an item is used."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.currency import unit_rate
from app.core.sheets import sheet_response
from app.schemas.item_master import BulkCategoryIn, BulkStatusIn, CategoryIn, CategoryPatch, MasterItemIn, StatusIn
from app.services import item_master as im
from app.services import item_usage
from app.services.site_rates import current_lines_of_item

router = APIRouter()

SORTS = {"code": models.DBItem.item_code, "name": models.DBItem.item_name, "category": models.DBItem.item_category,
         "subcategory": models.DBItem.item_subcategory, "type": models.DBItem.item_type, "uom": models.DBItem.units_of_measure,
         "rate": models.DBItem.selling_rate, "status": models.DBItem.is_active}


def _item(db, client_id, item_id):
    item = db.query(models.DBItem).filter(models.DBItem.id == item_id, models.DBItem.client_id == client_id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    return item


def _filtered(db, client_id, q, category, subcategory, item_type, uom, status, kind, site_id):
    query = db.query(models.DBItem).filter(models.DBItem.client_id == client_id)
    if q:
        like = "%" + q.strip() + "%"
        query = query.filter(or_(models.DBItem.item_code.ilike(like), models.DBItem.item_name.ilike(like),
                                 models.DBItem.description.ilike(like), models.DBItem.specification.ilike(like)))
    for column, value in ((models.DBItem.item_category, category), (models.DBItem.item_subcategory, subcategory),
                          (models.DBItem.item_type, item_type), (models.DBItem.units_of_measure, uom), (models.DBItem.kind, (kind or "").upper())):
        if value:
            query = query.filter(column == value)
    if status == "active":
        query = query.filter(models.DBItem.is_active.isnot(False))
    elif status == "inactive":
        query = query.filter(models.DBItem.is_active.is_(False))
    if site_id:
        codes = [l.item_code for l in current_lines_of_item(db, client_id, site_id)]
        query = query.filter(models.DBItem.item_code.in_(codes or [""]))
    return query


@router.get("/api/items")
def items_list(request: Request, q: str = "", category: str = "", subcategory: str = "", item_type: str = "", uom: str = "",
               status: str = "all", kind: str = "", site_id: Optional[int] = None, sort: str = "code", direction: str = "asc",
               page: int = 1, page_size: int = 25, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    query = _filtered(db, client.id, q, category, subcategory, item_type, uom, status, kind, site_id)
    total = query.count()
    column = SORTS.get(sort, models.DBItem.item_code)
    order = column.desc() if direction == "desc" else column.asc()
    page_size = max(1, min(page_size, 200))
    rows = query.order_by(order, models.DBItem.id).offset((max(1, page) - 1) * page_size).limit(page_size).all()
    codes = [r.item_code for r in rows]
    used, stock = im.sites_using(db, client.id, codes), im.stock_of(db, client.id, codes)
    return {"items": [im.item_dict(r, len(used.get(r.item_code, ())), stock.get(r.item_code, 0.0)) for r in rows], "total": total,
            "page": max(1, page), "page_size": page_size}


def _owned(db, client_id, ids):
    ids = list(dict.fromkeys(ids or []))
    if not ids:
        raise HTTPException(422, "Choose at least one item.")
    if len(ids) > 1000:
        raise HTTPException(422, "Choose at most 1,000 items at a time.")
    items = db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.id.in_(ids)).all()
    if len(items) != len(ids):
        raise HTTPException(404, "Some of those items no longer exist. Refresh the list and try again.")
    return items


@router.post("/api/items/bulk-status")
def items_bulk_status(body: BulkStatusIn, request: Request, db: Session = Depends(get_db)):
    """Switch several items on or off together. All or none."""
    client, _, who = wo_actor(request, db, "items.manage")
    items = _owned(db, client.id, body.ids)
    if not body.is_active and not body.confirm:
        busy = item_usage.used_codes(db, client.id, [i.item_code for i in items if i.is_active is not False])
        if busy:
            raise HTTPException(409, "%d of these %d item%s %s used on BOQs, orders or in the store. %s stay on those documents, but can no longer be put on new lines. Confirm to deactivate them anyway."
                                % (len(busy), len(items), "" if len(items) == 1 else "s", "is" if len(busy) == 1 else "are", "It" if len(busy) == 1 else "They"))
    for item in items:
        item.is_active, item.updated_by_name, item.updated_at = body.is_active, who, im.now()
    log_audit(db, client.id, "items_activated" if body.is_active else "items_deactivated", "item", None, "", "%d items" % len(items), request)
    db.commit()
    return {"changed": len(items), "message": "%d item%s %s." % (len(items), "" if len(items) == 1 else "s", "activated" if body.is_active else "deactivated")}


@router.post("/api/items/bulk-category")
def items_bulk_category(body: BulkCategoryIn, request: Request, db: Session = Depends(get_db)):
    """Move several items to another category (and subcategory). All or none."""
    client, _, who = wo_actor(request, db, "items.manage")
    items = _owned(db, client.id, body.ids)
    category, subcategory = im.check_category(db, client.id, body.item_category, body.item_subcategory)
    for item in items:
        item.item_category, item.item_subcategory, item.updated_by_name, item.updated_at = category, subcategory, who, im.now()
    log_audit(db, client.id, "items_recategorised", "item", None, category, "%d items" % len(items), request)
    db.commit()
    return {"changed": len(items), "message": "%d item%s moved to %s." % (len(items), "" if len(items) == 1 else "s", category or "no category")}


@router.get("/api/items/next-code")
def item_next_code(request: Request, db: Session = Depends(get_db)):
    """The next free code, offered when someone starts a new item. Nothing is reserved: they can type their own."""
    require_erp_read(request, db)
    return {"code": im.peek_next_code(db)}


@router.get("/api/items/similar")
def item_similar(request: Request, name: str = "", code: str = "", exclude_id: Optional[int] = None, db: Session = Depends(get_db)):
    """What already looks like this name or code, so a repeat is noticed before it is saved."""
    client = require_erp_read(request, db)
    return {"similar": im.similar_items(db, client.id, name, code, exclude_id)}


@router.get("/api/items/export.xlsx")
def items_export(request: Request, q: str = "", category: str = "", subcategory: str = "", item_type: str = "", uom: str = "",
                 status: str = "all", kind: str = "", site_id: Optional[int] = None, ids: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    query = _filtered(db, client.id, q, category, subcategory, item_type, uom, status, kind, site_id)
    picked = [int(i) for i in ids.split(",") if i.strip().isdigit()]
    if picked:
        query = query.filter(models.DBItem.id.in_(picked))          # the rows ticked on screen, when some are
    rows = query.order_by(models.DBItem.item_code).all()
    used = im.sites_using(db, client.id, [r.item_code for r in rows])
    headers = ["Item Code", "Item Name", "Description", "Category", "Subcategory", "Item Type", "UOM", "Specification",
               "Default Purchase Rate", "Default Selling Rate", "HSN/SAC", "GST", "Sites Using", "Status"]
    body = [[r.item_code, r.item_name, r.description or "", r.item_category or "", r.item_subcategory or "", r.item_type or "",
             r.units_of_measure or "", r.specification or "", unit_rate(r.purchase_rate), unit_rate(r.selling_rate), r.hsn_code or "",
             r.item_tax_type or "", len(used.get(r.item_code, ())), "Active" if r.is_active is not False else "Inactive"] for r in rows]
    return sheet_response(headers, body, "item_master.xlsx")


@router.get("/api/items/{item_id}")
def item_get(item_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    item = _item(db, client.id, item_id)
    return {"item": im.item_dict(item, len(im.sites_using(db, client.id, [item.item_code]).get(item.item_code, ())))}


@router.post("/api/items")
def item_create(body: MasterItemIn, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, "items.manage")
    try:
        item = im.create_master_item(db, client.id, body, who)
        log_audit(db, client.id, "item_created", "item", item.id, item.item_code, item.item_name, request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"item": im.item_dict(item), "message": "%s added." % item.item_code}


@router.put("/api/items/{item_id}")
def item_update(item_id: int, body: MasterItemIn, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, "items.manage")
    item = _item(db, client.id, item_id)
    try:
        im.update_master_item(db, item, body, who)
        log_audit(db, client.id, "item_updated", "item", item.id, item.item_code, item.item_name, request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"item": im.item_dict(item), "message": "%s updated." % item.item_code}


@router.patch("/api/items/{item_id}/status")
def item_status(item_id: int, body: StatusIn, request: Request, db: Session = Depends(get_db)):
    """Switch an item off or on. Nothing that already uses it is touched; it just cannot be picked for new lines."""
    client, _, who = wo_actor(request, db, "items.manage")
    item = _item(db, client.id, item_id)
    if not body.is_active and item.is_active is not False and not body.confirm:
        usage = item_usage.where_used(db, client.id, item)
        if usage["total"]:
            raise HTTPException(409, "'%s' is used in %d place%s (%s). It stays on them, but can no longer be put on new lines. Confirm to deactivate it anyway."
                                % (item.item_name, usage["total"], "" if usage["total"] == 1 else "s", ", ".join("%s %d" % (g["label"], g["count"]) for g in usage["groups"])))
    item.is_active, item.updated_by_name, item.updated_at = body.is_active, who, im.now()
    log_audit(db, client.id, "item_activated" if body.is_active else "item_deactivated", "item", item.id, item.item_code, "", request)
    db.commit()
    return {"item": im.item_dict(item), "message": "%s %s." % (item.item_code, "activated" if body.is_active else "deactivated")}


@router.get("/api/items/{item_id}/where-used")
def item_where_used(item_id: int, request: Request, db: Session = Depends(get_db)):
    """Every BOQ, order and store record that carries the item's code, so nobody switches off something still in use unknowingly."""
    client = require_erp_read(request, db)
    item = _item(db, client.id, item_id)
    return {"item": im.item_dict(item, len(im.sites_using(db, client.id, [item.item_code]).get(item.item_code, ())),
                                 im.stock_of(db, client.id, [item.item_code]).get(item.item_code, 0.0)), **item_usage.where_used(db, client.id, item)}


@router.get("/api/items/{item_id}/sites")
def item_sites(item_id: int, request: Request, db: Session = Depends(get_db)):
    """Every site whose current BOQ uses the item, with that site's quantity and rate."""
    client = require_erp_read(request, db)
    item = _item(db, client.id, item_id)
    rates = {r.job_id: r for r in db.query(models.DBSiteItemRate).filter(models.DBSiteItemRate.item_id == item.id).all()}
    out = []
    for line in current_lines_of_item(db, client.id, None, item.item_code):
        boq = db.query(models.DBBoq).filter(models.DBBoq.id == line.boq_id).first()
        job = db.query(models.DBJob).filter(models.DBJob.id == boq.job_id).first() if boq else None
        if not job:
            continue
        rate = rates.get(job.id)
        out.append({"site_id": job.id, "site_code": job.number or "", "site_name": job.name or "", "boq_number": boq.number or "",
                    "quantity": line.quantity or 0, "boq_rate": unit_rate(line.rate),
                    "site_rate": rate.site_rate if rate is not None else None,
                    "status": (rate.status if rate is not None and rate.site_rate is not None else "Pending")})
    return {"item": im.item_dict(item, len(out)), "sites": out}


# --- the categories a business files its items under --------------------------------------------------------------------

def _tree(db, client_id):
    im.ensure_default_categories(db, client_id)
    rows = db.query(models.DBItemCategory).filter(models.DBItemCategory.client_id == client_id).order_by(models.DBItemCategory.name).all()
    kids = {}
    for r in rows:
        if r.parent_id:
            kids.setdefault(r.parent_id, []).append({"id": r.id, "name": r.name, "is_active": r.is_active is not False})
    return [{"id": r.id, "name": r.name, "is_active": r.is_active is not False, "subcategories": kids.get(r.id, [])}
            for r in rows if not r.parent_id]


@router.get("/api/item-categories")
def categories_list(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    tree = _tree(db, client.id)
    db.commit()
    return {"categories": tree}


@router.post("/api/item-categories")
def category_create(body: CategoryIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "items.manage")
    name = " ".join((body.name or "").split())
    if not name:
        raise HTTPException(400, "A name is required.")
    im.ensure_default_categories(db, client.id)
    if body.parent_id and not db.query(models.DBItemCategory.id).filter(
            models.DBItemCategory.id == body.parent_id, models.DBItemCategory.client_id == client.id,
            models.DBItemCategory.parent_id.is_(None)).first():
        raise HTTPException(404, "That category does not exist.")
    clash = db.query(models.DBItemCategory.id).filter(
        models.DBItemCategory.client_id == client.id, func.lower(models.DBItemCategory.name) == name.lower(),
        models.DBItemCategory.parent_id.is_(None) if not body.parent_id else models.DBItemCategory.parent_id == body.parent_id).first()
    if clash:
        raise HTTPException(409, "%s already exists." % name)
    db.add(models.DBItemCategory(client_id=client.id, parent_id=body.parent_id, name=name))
    db.commit()
    return {"categories": _tree(db, client.id), "message": "%s added." % name}


@router.patch("/api/item-categories/{category_id}")
def category_update(category_id: int, body: CategoryPatch, request: Request, db: Session = Depends(get_db)):
    """Rename or switch off a category. Items filed under a renamed one are moved with it."""
    client, _, _ = wo_actor(request, db, "items.manage")
    cat = db.query(models.DBItemCategory).filter(models.DBItemCategory.id == category_id, models.DBItemCategory.client_id == client.id).first()
    if not cat:
        raise HTTPException(404, "Category not found")
    if body.name is not None:
        name = " ".join(body.name.split())
        if not name:
            raise HTTPException(400, "A name is required.")
        if name.lower() != cat.name.lower() and db.query(models.DBItemCategory.id).filter(
                models.DBItemCategory.client_id == client.id, models.DBItemCategory.parent_id == cat.parent_id,
                func.lower(models.DBItemCategory.name) == name.lower()).first():
            raise HTTPException(409, "%s already exists." % name)
        column = models.DBItem.item_subcategory if cat.parent_id else models.DBItem.item_category
        scope = [column == cat.name, models.DBItem.client_id == client.id]
        if cat.parent_id:
            parent = db.query(models.DBItemCategory).get(cat.parent_id)
            scope.append(models.DBItem.item_category == parent.name)
        db.query(models.DBItem).filter(and_(*scope)).update({column: name}, synchronize_session=False)
        cat.name = name
    if body.is_active is not None:
        cat.is_active = body.is_active
    db.commit()
    return {"categories": _tree(db, client.id), "message": "Saved."}
