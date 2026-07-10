"""知识管理 API — Qdrant 状态、章节列表"""

from pathlib import Path
from fastapi import APIRouter, HTTPException
from qdrant_client import QdrantClient
from academic_companion.config import get_config

router = APIRouter()


@router.get("/knowledge/status")
async def knowledge_status():
    """获取 Qdrant 向量库统计"""
    config = get_config()
    try:
        client = QdrantClient(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key,
            timeout=10,
        )
        collections = client.get_collections()
        result = {}
        for c in collections.collections:
            try:
                info = client.get_collection(c.name)
                result[c.name] = {
                    "points_count": info.points_count,
                    "vectors_count": info.vectors_count,
                    "indexed_vectors_count": info.indexed_vectors_count,
                }
            except Exception:
                result[c.name] = {"error": "无法获取统计"}
        return {
            "qdrant_url": config.qdrant_url,
            "collections": result,
            "total_collections": len(collections.collections),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Qdrant 连接失败: {str(e)}")


@router.get("/knowledge/chapters")
async def list_chapters():
    """列出 CS-Base 所有章节及文章"""
    data_dir = Path(__file__).resolve().parents[2] / "data" / "cs_fundamentals" / "CS-Base"
    if not data_dir.exists():
        return {"chapters": [], "message": "数据目录不存在"}

    subjects = {}
    for subject_dir in sorted(data_dir.iterdir()):
        if not subject_dir.is_dir() or subject_dir.name.startswith("."):
            continue
        name = subject_dir.name
        if name in ("cs_learn", "reader_nb", "README.md"):
            continue
        sub_dirs = [d for d in subject_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        chapters = []
        for sub in sorted(sub_dirs):
            md_files = sorted(sub.rglob("*.md"))
            chapters.append({
                "id": f"{name}/{sub.name}",
                "name_zh": sub.name,
                "subject": name,
                "article_count": len(md_files),
                "article_titles": [f.stem for f in md_files],
            })
        if chapters:
            subjects[name] = chapters

    return {"subjects": subjects, "total_chapters": sum(len(c) for c in subjects.values())}
