from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.demo import DemoDataImportRequest, DemoDataStatusRead
from zhiju.services.demo import delete_feishu_demo, demo_status, import_feishu_demo
from zhiju.services.identity import ConflictError


router = APIRouter(prefix="/v3/demo-data", tags=["demo-data"])


@router.get("/feishu-first20", response_model=DemoDataStatusRead)
def get_feishu_demo_status(session: Session = Depends(get_db)) -> DemoDataStatusRead:
    return demo_status(session)


@router.post("/feishu-first20", response_model=DemoDataStatusRead)
def post_feishu_demo(
    payload: DemoDataImportRequest,
    session: Session = Depends(get_db),
) -> DemoDataStatusRead:
    try:
        return import_feishu_demo(session, payload)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/feishu-first20", response_model=DemoDataStatusRead)
def delete_feishu_demo_data(session: Session = Depends(get_db)) -> DemoDataStatusRead:
    try:
        return delete_feishu_demo(session)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
