from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.business import Business

router = APIRouter()


class BusinessUpdate(BaseModel):
    meta_page_access_token: Optional[str] = None
    base_prompt: Optional[str] = None
    meta_waba_id: Optional[str] = None
    meta_phone_number_id: Optional[str] = None


@router.get("/admin/businesses")
def list_businesses(db: Session = Depends(get_db)):
    businesses = db.query(Business).all()
    return [
        {
            "id": str(b.id),
            "name": b.name,
            "tier": b.tier,
            "meta_phone_number_id": b.meta_phone_number_id,
            "meta_waba_id": b.meta_waba_id,
            "has_page_token": bool(b.meta_page_access_token),
        }
        for b in businesses
    ]


@router.patch("/admin/businesses/{business_id}")
def update_business(business_id: str, update: BusinessUpdate, db: Session = Depends(get_db)):
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        return {"error": "Business not found"}

    for field, value in update.dict(exclude_none=True).items():
        setattr(business, field, value)

    db.commit()
    return {"status": "updated", "name": business.name}