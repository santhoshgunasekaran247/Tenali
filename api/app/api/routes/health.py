from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def root():
    return {
        "application": "Tenali",
        "message": "Tenali Business System API is running",
        "status": "ok",
    }


@router.get("/health")
def health():
    return {"application": "Tenali", "status": "healthy"}
