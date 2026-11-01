from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from zhiju.auth_context import get_tenant_db
from zhiju.api.v14 import operator, call
from zhiju.permissions import require_platform_permission
from zhiju.services import skill_catalog as service

router=APIRouter(prefix='/v3/skill-categories',tags=['skill-categories'])

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1,max_length=80)
    description: str = Field(default='',max_length=2000)
class DefaultVersion(BaseModel):
    version_id: str

def invoke(fn,*args):
    try:return call(fn,*args)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@router.get('')
def listing(s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return service.catalog(s)

@router.post('',dependencies=[Depends(require_platform_permission)])
def create(body:CategoryCreate,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return invoke(service.create_category,s,body.name,body.description)

@router.post('/{category_id}/versions',dependencies=[Depends(require_platform_permission)])
def upload(category_id:str,label:str=Form(...),change_summary:str=Form(''),file:UploadFile=File(...),s:Session=Depends(get_tenant_db),p=Depends(operator)):
    data=file.file.read(8*1024*1024+1)
    if len(data)>8*1024*1024:raise HTTPException(422,'Skills ZIP 超过 8 MiB')
    return invoke(service.upload,s,category_id,label,change_summary,data)

@router.post('/{category_id}/default')
def default(category_id:str,body:DefaultVersion,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return invoke(service.select_default,s,category_id,body.version_id)

@router.post('/{category_id}/versions/{version_id}/publish',dependencies=[Depends(require_platform_permission)])
def publish(category_id:str,version_id:str,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return invoke(service.publish,s,category_id,version_id)

@router.get('/{category_id}/versions/{version_id}/download')
def download(category_id:str,version_id:str,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return Response(invoke(service.archive,s,category_id,version_id),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="skills.zip"'})

@router.get('/{category_id}/versions/{version_id}')
def detail(category_id:str,version_id:str,path:str|None=None,s:Session=Depends(get_tenant_db),p=Depends(operator)):
    data=invoke(service.archive,s,category_id,version_id)
    if category_id==service.PRODUCTION:
        from zhiju.workflow_bundles import inspect_bundle,read_file
        result=inspect_bundle(data)
        if path:
            if path not in result['files']:raise HTTPException(422,'文件不在此版本中')
            result['content']=invoke(read_file,data,path)
        return result
    content=invoke(service.files,data)
    if path and path not in content:raise HTTPException(422,'文件不在此版本中')
    return {'files':sorted(content),'content':content.get(path) if path else None}


@router.post('/channel-initialization/sync',dependencies=[Depends(require_platform_permission)])
def sync_initialization(s:Session=Depends(get_tenant_db),p=Depends(operator)):
    return invoke(service.sync_initialization,s)
