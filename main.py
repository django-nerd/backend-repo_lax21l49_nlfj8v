import os
from io import BytesIO
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from database import get_db, create_document, get_documents
from schemas import Dataset, ChartView

import pandas as pd

app = FastAPI(title="Doc2Charts API", version="0.1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UploadResponse(BaseModel):
    dataset_id: str
    columns: List[str]
    sample: List[Dict[str, Any]]


@app.get("/")
def read_root():
    return {"message": "Doc2Charts Backend Running"}


@app.get("/test")
def test_database():
    response = {"backend": "✅ Running", "database": "❌ Not Available"}
    try:
        db = get_db()
        if db is not None:
            _ = db.list_collection_names()
            response["database"] = "✅ Connected"
    except Exception as e:
        response["database"] = f"⚠️ {str(e)[:80]}"
    return response


# ---------- Parsing Helpers ----------

def dataframe_from_file(file: UploadFile) -> pd.DataFrame:
    filename = file.filename or "uploaded"
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    ext = os.path.splitext(filename)[1].lower()
    buffer = BytesIO(content)

    try:
        if ext in [".csv"]:
            return pd.read_csv(buffer)
        if ext in [".xls", ".xlsx"]:
            return pd.read_excel(buffer)
        if ext in [".txt"]:
            # Try tab or comma separated
            try:
                return pd.read_csv(buffer, sep="\t")
            except Exception:
                buffer.seek(0)
                return pd.read_csv(buffer)
        # Simple PDF table extraction using tabula optional would require Java; skip for now
        raise HTTPException(status_code=400, detail="Unsupported file type. Use CSV, XLS, XLSX, or TXT.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)[:120]}")


# ---------- API Endpoints ----------

@app.post("/api/upload", response_model=UploadResponse)
async def upload_dataset(
    file: UploadFile = File(...),
    user_id: Optional[str] = Form(None)
):
    df = dataframe_from_file(file)
    if df.empty or df.shape[1] == 0:
        raise HTTPException(status_code=400, detail="No tabular data found.")

    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    df = df.infer_objects(copy=False)

    columns = [str(c) for c in df.columns]
    rows = df.to_dict(orient="records")
    sample = rows[:50]

    dataset = Dataset(
        user_id=user_id,
        filename=file.filename or "uploaded",
        filetype=os.path.splitext(file.filename or "uploaded")[1].lower().strip('.') or "unknown",
        columns=columns,
        rows=rows,
        sample=sample,
    )

    dataset_id = create_document("dataset", dataset)

    return UploadResponse(dataset_id=dataset_id, columns=columns, sample=sample)


class ChartRequest(BaseModel):
    dataset_id: str
    x_key: str
    y_key: str
    chart_type: str
    user_id: Optional[str] = None


@app.post("/api/chart/save")
async def save_chart(cfg: ChartRequest):
    # validate dataset exists
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    existing = db["dataset"].find_one({"_id": cfg.dataset_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Dataset not found")

    chart = ChartView(
        user_id=cfg.user_id,
        dataset_id=cfg.dataset_id,
        x_key=cfg.x_key,
        y_key=cfg.y_key,
        chart_type=cfg.chart_type,
    )
    chart_id = create_document("chartview", chart)
    return {"chart_id": chart_id}


@app.get("/api/history")
async def history(user_id: Optional[str] = None, limit: int = 20):
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    filt = {"user_id": user_id} if user_id else {}
    items = get_documents("dataset", filt, limit)
    # Minimal projection
    for it in items:
        it["_id"] = str(it.get("_id"))
    return {"datasets": items}


@app.get("/api/dataset/{dataset_id}")
async def get_dataset(dataset_id: str, limit: int = 1000):
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    doc = db["dataset"].find_one({"_id": dataset_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # If very large, slice rows
    if isinstance(limit, int) and limit > 0:
        doc["rows"] = doc.get("rows", [])[:min(limit, 5000)]
    # Ensure id is a string
    doc["_id"] = str(doc.get("_id"))
    return doc


# Simple AI insight stub (can be replaced by a real model)
class InsightRequest(BaseModel):
    dataset_id: str
    question: Optional[str] = None


@app.post("/api/insights")
async def insights(req: InsightRequest):
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    doc = db["dataset"].find_one({"_id": req.dataset_id}, {"rows": 1, "columns": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = pd.DataFrame(doc.get("rows", []))
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    insights = []
    for col in numeric_cols[:5]:
        series = df[col].dropna()
        insights.append({
            "metric": col,
            "count": int(series.count()),
            "mean": float(series.mean()) if not series.empty else None,
            "min": float(series.min()) if not series.empty else None,
            "max": float(series.max()) if not series.empty else None,
        })

    return {"columns": doc.get("columns", []), "numeric_columns": numeric_cols, "stats": insights, "note": "This is a local heuristic summary."}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
