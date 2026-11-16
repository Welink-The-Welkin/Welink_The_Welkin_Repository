"""背景图片路由"""
from pathlib import Path
import random
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/background", tags=["background"])

# 背景图片目录 - 相对于项目根目录
BACKGROUND_DIR = Path(__file__).resolve().parents[4] / "assets" / "backgrounds"

# 固定背景页面映射
FIXED_BACKGROUNDS = {
    "home": "过去与现在.jpeg",      # 主菜单
    "stories": "过去与现在.jpeg",   # 剧情目录
    "game": "流浪者正面.jpeg",      # 剧情旅途
    "intro": "流浪者背面.jpeg"      # 角色与玩法
}

# 自由对话页面的随机背景池
CHAT_BACKGROUNDS = [
    "流浪者与兰那罗3.jpeg",
    "流浪者背面.jpeg",
    "流浪者正面.jpeg",
    "倾帽.jpg",
    "咕咕嘎嘎.jpg"
]


@router.get("/{route_name}")
async def get_background(route_name: str):
    """根据路由名称返回对应的背景图片

    - home、stories、game、intro 使用固定背景
    - chat 从预设图片池中随机选择
    """
    # 检查是否是固定背景页面
    if route_name in FIXED_BACKGROUNDS:
        filename = FIXED_BACKGROUNDS[route_name]
    # chat 页面随机选择背景
    elif route_name == "chat":
        filename = random.choice(CHAT_BACKGROUNDS)
    else:
        raise HTTPException(status_code=404, detail="背景图片未找到")

    file_path = BACKGROUND_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"图片文件不存在: {filename}")

    cache_control = "no-store" if route_name == "chat" else "public, max-age=86400"
    return FileResponse(
        path=file_path,
        media_type=f"image/{file_path.suffix[1:]}",
        headers={"Cache-Control": cache_control},
    )
