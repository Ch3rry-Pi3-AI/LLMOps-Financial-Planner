"""
Database package initialisation for the **Alex Financial Planner** backend.

This module provides a clean, centralised export surface for all
database-related components used across the application, including:

• The main `Database` class — high-level interface for queries  
• The `DataAPIClient` — low-level client for Data API interactions  
• All Pydantic schemas used for input validation and API responses  
• Enum types for regions, sectors, asset classes, job types, and more  

It allows other modules to import from `src` directly without needing to know
the internal structure of the database layer.

Example:
    from src import Database, UserCreate

The `__all__` list ensures that only the intended public symbols are exposed
when performing wildcard imports.

This file contributes to the backend by acting as the **public interface**
for the database subsystem, improving modularity and keeping the import
surface stable as internal implementation details evolve.
"""

from .client import DataAPIClient
from .models import Database
from .schemas import (
    # Types
    RegionType,
    AssetClassType,
    SectorType,
    InstrumentType,
    JobType,
    JobStatus,
    AccountType,
    
    # Create schemas (for inputs)
    InstrumentCreate,
    UserCreate,
    AccountCreate,
    PositionCreate,
    JobCreate,
    JobUpdate,
    
    # Response schemas (for outputs)
    InstrumentResponse,
    PortfolioAnalysis,
    RebalanceRecommendation,
)

__all__ = [
    'Database',
    'DataAPIClient',
    'InstrumentCreate',
    'UserCreate',
    'AccountCreate',
    'PositionCreate',
    'JobCreate',
    'JobUpdate',
    'InstrumentResponse',
    'PortfolioAnalysis',
    'RebalanceRecommendation',
    'RegionType',
    'AssetClassType',
    'SectorType',
    'InstrumentType',
    'JobType',
    'JobStatus',
    'AccountType',
]
