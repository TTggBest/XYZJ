from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from zhiju.auth_context import get_tenant_db
from zhiju.services.xiaowu_sync import BINDING_HEADERS, CID_HEADERS, binding_context, export_workbook, match_binding, parse_binding, parse_cid

router = APIRouter(prefix='/v3/xiaowu-sync', tags=['xiaowu-sync'])


@router.post('/preview/{kind}')
def preview(kind: Literal['binding','cid'], files: list[UploadFile] = File(...), session: Session = Depends(get_tenant_db)):
    if kind=='binding' and len(files)!=1:
        raise HTTPException(422,'视频绑定每次上传一个 XLSX 文件')
    rows=[]
    try:
        for file in files:
            filename=file.filename or '未命名文件'
            if not filename.lower().endswith('.xlsx' if kind=='binding' else '.csv'):
                raise ValueError('视频绑定需要 XLSX，解 CID 需要 CSV')
            content=file.file.read()
            rows.extend(parse_binding(content,filename) if kind=='binding' else parse_cid(content,filename))
        if kind=='binding': rows=match_binding(rows,binding_context(session,rows))
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {'kind':kind,'headers': BINDING_HEADERS if kind=='binding' else CID_HEADERS,'rows':rows,
            'file_count':len(files),'total':len(rows),'issue_count':sum(bool(r['issues']) for r in rows)}


class ExportRequest(BaseModel):
    kind: Literal['binding','cid']
    rows: list[dict]


@router.post('/export')
def export(payload: ExportRequest, session: Session = Depends(get_tenant_db)):
    try:
        content=export_workbook(payload.kind,payload.rows)
    except (ValueError,KeyError,TypeError) as exc:
        raise HTTPException(422,str(exc)) from exc
    filename='小五视频绑定.xlsx' if payload.kind=='binding' else '小五解CID汇总.xlsx'
    return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':f"attachment; filename*=UTF-8''{quote(filename)}"})
