import os

from fastapi import APIRouter, Depends, File as UploadFileParam, UploadFile
from sqlmodel import Session

from app.core.auth import get_current_user, resolve_current_user_id
from app.core.response import api_error, api_success
from app.database import engine
from app.models import File as FileModel

router = APIRouter(prefix="/upload", tags=["Upload"])

UPLOAD_DIR = "documents"


@router.post("")
async def upload_file(
    file: UploadFile = UploadFileParam(...),
    current_user: dict = Depends(get_current_user),
):
    with Session(engine) as session:
        user_id = resolve_current_user_id(current_user, session)

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    stored_filename = f"{user_id}__{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, stored_filename)

    # Save file to disk
    with open(filepath, "wb") as f:
        f.write(await file.read())

    # Write DB record
    with Session(engine) as session:
        db_file = FileModel(
            filename=file.filename,
            filepath=filepath,
            source="user",
            user_id=user_id,
        )
        session.add(db_file)
        session.commit()
        session.refresh(db_file)

    # ---- Incremental vector indexing (was full rebuild) ------------------
    try:
        from utils.vector_store import add_file_to_store
        chunk_count = add_file_to_store(filepath, file.filename, user_id)
        # Refresh BM25 index so new chunks are searchable
        from app.services.rag_service import rebuild_bm25
        rebuild_bm25()
    except Exception as exc:
        # Rollback: remove file + DB record on indexing failure
        if os.path.exists(filepath):
            os.remove(filepath)
        with Session(engine) as session:
            stored_file = session.get(FileModel, db_file.id)
            if stored_file is not None:
                session.delete(stored_file)
                session.commit()
        return api_error(f"上传失败: {exc}", status_code=500)

    return api_success(
        "上传成功，知识库已更新",
        {
            "file_id": db_file.id,
            "filename": file.filename,
            "chunks_added": chunk_count,
        },
    )
