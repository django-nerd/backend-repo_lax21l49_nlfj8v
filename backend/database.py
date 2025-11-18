"""
Database Helper Functions

MongoDB helper functions ready to use in your backend code.
Import and use these functions in your API endpoints for database operations.
"""

from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from typing import Union, Optional, Any, Dict
from pydantic import BaseModel
import uuid

# Load environment variables from .env file
load_dotenv()

_client = None
_db = None


def get_db():
    """Lazily initialize and return the MongoDB database handle.
    Avoids importing pymongo at module import time to prevent conflicts
    with the standalone 'bson' package in some environments.
    """
    global _client, _db
    if _db is not None:
        return _db
    database_url = os.getenv("DATABASE_URL")
    database_name = os.getenv("DATABASE_NAME")
    if not (database_url and database_name):
        return None
    try:
        from pymongo import MongoClient  # Local import to avoid early failures
        _client = MongoClient(database_url)
        _db = _client[database_name]
        return _db
    except Exception:
        _db = None
        return None


# Helper functions for common database operations

def create_document(collection_name: str, data: Union[BaseModel, Dict[str, Any]]):
    """Insert a single document with timestamp. Ensures string _id for portability."""
    db = get_db()
    if db is None:
        raise Exception("Database not available. Check DATABASE_URL and DATABASE_NAME environment variables.")

    # Convert Pydantic model to dict if needed
    if isinstance(data, BaseModel):
        data_dict = data.model_dump()
    else:
        data_dict = dict(data)

    # Ensure string _id to avoid bson dependency
    data_dict.setdefault("_id", uuid.uuid4().hex)

    now = datetime.now(timezone.utc)
    data_dict['created_at'] = now
    data_dict['updated_at'] = now

    result = db[collection_name].insert_one(data_dict)
    # Return our chosen _id (string) for consistency
    return str(data_dict["_id"])


def get_documents(collection_name: str, filter_dict: dict = None, limit: int = None):
    """Get documents from collection"""
    db = get_db()
    if db is None:
        raise Exception("Database not available. Check DATABASE_URL and DATABASE_NAME environment variables.")

    cursor = db[collection_name].find(filter_dict or {})
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)
