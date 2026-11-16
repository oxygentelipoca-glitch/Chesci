import os
from pathlib import Path

import chromadb
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_user, resolve_current_user_id
from app.core.response import api_success
from app.database import engine
from app.models import File
from utils.vector_store import sync_system_documents



router = APIRouter(

    prefix="/files",

    tags=["Files"]

)



# Chroma客户端

chroma_client = chromadb.PersistentClient(

    path="vector_db"

)


collection = chroma_client.get_collection(

    "knowledge"

)


def _system_documents(folder_path: str = "documents"):
    documents_dir = Path(folder_path)
    if not documents_dir.exists():
        return []

    system_files = []
    for path in documents_dir.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        if "__" in path.name:
            continue

        system_files.append(
            {
                "key": f"system:{path.name}",
                "id": f"system:{path.name}",
                "filename": path.name,
                "filepath": str(path),
                "source": "system",
                "can_delete": False,
            }
        )

    return system_files


@router.get("/status")
def get_index_status(current_user: dict = Depends(get_current_user)):
    """Return index freshness and retriever status for the knowledge panel."""
    with Session(engine) as session:
        resolve_current_user_id(current_user, session)

    indexed = collection.get(include=["metadatas"])
    metadatas = indexed.get("metadatas") or []
    system_names = {item["filename"] for item in _system_documents()}
    indexed_system_names = {
        meta.get("filename")
        for meta in metadatas
        if meta.get("user_id") == "system"
    }
    from app.services.rag_service import retrieval_status
    return api_success(
        "获取索引状态成功",
        {
            "indexed_chunks": len(indexed.get("ids") or []),
            "system_documents": len(system_names),
            "system_documents_indexed": len(system_names & indexed_system_names),
            "system_index_is_current": system_names == indexed_system_names,
            "retrieval": retrieval_status(),
        },
    )


@router.post("/reindex-system")
def reindex_system_documents(current_user: dict = Depends(get_current_user)):
    """Incrementally refresh built-in documents without deleting user uploads."""
    with Session(engine) as session:
        resolve_current_user_id(current_user, session)

    chunk_count = sync_system_documents()
    from app.services.rag_service import rebuild_bm25
    rebuild_bm25()
    return api_success("内置知识库已同步", {"chunks_added": chunk_count})




# 获取文件列表

@router.get("")
def get_files(current_user: dict = Depends(get_current_user)):


    with Session(engine) as session:
        user_id = resolve_current_user_id(current_user, session)


        user_files = session.exec(
            select(File).where(File.user_id == user_id)

        ).all()

        response = [
            {
                "key": f"user:{file.id}",
                "id": file.id,
                "filename": file.filename,
                "filepath": file.filepath,
                "source": file.source,
                "can_delete": True,
            }
            for file in user_files
        ]
        response.extend(_system_documents())

        return api_success("获取文件列表成功", response)





# 删除文件

@router.delete("/{file_id}")
def delete_file(
    file_id: int,
    current_user: dict = Depends(get_current_user),
):


    with Session(engine) as session:
        user_id = resolve_current_user_id(current_user, session)



        file = session.get(
            File,

            file_id

        )



        if not file or file.user_id != user_id:


            raise HTTPException(

                status_code=404,

                detail="文件不存在"

            )



        filename = file.filename



        filepath = file.filepath
        stored_filename = os.path.basename(filepath)



        # =====================
        # 删除Chroma向量
        # =====================


        try:


            collection.delete(
                where={
                    "stored_filename":
                    stored_filename,
                    "user_id":
                    str(user_id)
                }

            )


        except Exception as e:


            print(

                "删除向量失败:",
                e

            )





        # =====================
        # 删除本地文件
        # =====================


        if os.path.exists(filepath):


            os.remove(filepath)




        # =====================
        # 删除数据库
        # =====================


        session.delete(file)


        session.commit()

        # Refresh BM25 index after removing vectors
        from app.services.rag_service import rebuild_bm25
        rebuild_bm25()

        return api_success("删除成功", None)
