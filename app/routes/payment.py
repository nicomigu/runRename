from fastapi import APIRouter

router = APIRouter(prefix="/payment", tags=["payment"])


@router.get("/checkout")
async def checkout():
    return {"status": "not_implemented"}
