import sqlite3
import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
from pathlib import Path

from models import DropboxFile
from config import config

logger = logging.getLogger(__name__)

class LocalCacheService:
    def __init__(self, db_path: str = "dropbox_cache.db"):
        self.db_path = db_path
        self.init_database()
        logger.info(f"Local cache service initialized with database: {db_path}")
    
    def init_database(self):
        """Initialize SQLite database with required tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS files (
                        id TEXT PRIMARY KEY,
                        path_lower TEXT UNIQUE NOT NULL,
                        path_display TEXT NOT NULL,
                        name TEXT NOT NULL,
                        parent_path TEXT,
                        is_folder BOOLEAN NOT NULL DEFAULT 0,
                        file_type TEXT,
                        file_extension TEXT,
                        size INTEGER DEFAULT 0,
                        modified_date TEXT,
                        content_hash TEXT,
                        is_downloadable BOOLEAN DEFAULT 1,
                        last_synced TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes for faster queries
                conn.execute("CREATE INDEX IF NOT EXISTS idx_path_lower ON files(path_lower)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_parent_path ON files(parent_path)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_file_type ON files(file_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_modified_date ON files(modified_date)")
                
                # Metadata table for tracking sync state
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sync_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                conn.commit()
                logger.info("Database tables initialized successfully")
                
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def store_files(self, files: List[DropboxFile], is_full_sync: bool = False) -> int:
        """
        Store/update files in local cache
        
        Args:
            files: List of DropboxFile objects
            is_full_sync: If True, this is a complete sync (not incremental)
            
        Returns:
            Number of files stored/updated
        """
        try:
            stored_count = 0
            current_time = datetime.now().isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                for file in files:
                    # Determine parent path
                    parent_path = str(Path(file.path_display).parent) if file.path_display != "/" else None
                    if parent_path == "/":
                        parent_path = None
                    
                    # Insert or update file
                    cursor.execute("""
                        INSERT OR REPLACE INTO files (
                            id, path_lower, path_display, name, parent_path,
                            is_folder, file_type, file_extension, size, 
                            modified_date, content_hash, is_downloadable, last_synced
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        file.id,
                        file.path_lower,
                        file.path_display,
                        file.name,
                        parent_path,
                        False,  # We only store files, not folders in this implementation
                        file.file_type,
                        file.extension,
                        file.size,
                        file.modified.isoformat(),
                        file.content_hash,
                        file.is_downloadable,
                        current_time
                    ))
                    stored_count += 1
                
                # Update sync metadata
                cursor.execute("""
                    INSERT OR REPLACE INTO sync_metadata (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, ("last_sync", current_time, current_time))
                
                if is_full_sync:
                    cursor.execute("""
                        INSERT OR REPLACE INTO sync_metadata (key, value, updated_at)
                        VALUES (?, ?, ?)
                    """, ("last_full_sync", current_time, current_time))
                
                conn.commit()
                
            logger.info(f"Stored {stored_count} files in local cache")
            return stored_count
            
        except Exception as e:
            logger.error(f"Error storing files in cache: {e}")
            return 0
    
    def get_files(self, folder_path: str = None, file_types: List[str] = None) -> List[DropboxFile]:
        """
        Get files from local cache (instant, no API calls)
        
        Args:
            folder_path: Optional folder to filter by
            file_types: Optional list of file types to filter by
            
        Returns:
            List of DropboxFile objects from cache
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Build query
                query = "SELECT * FROM files WHERE is_folder = 0"
                params = []
                
                if folder_path:
                    if folder_path == "/":
                        query += " AND (parent_path IS NULL OR parent_path = '')"
                    else:
                        query += " AND parent_path LIKE ?"
                        params.append(f"{folder_path}%")
                
                if file_types:
                    placeholders = ",".join("?" * len(file_types))
                    query += f" AND file_type IN ({placeholders})"
                    params.extend(file_types)
                
                query += " ORDER BY path_display"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                # Convert to DropboxFile objects
                files = []
                for row in rows:
                    try:
                        file = DropboxFile(
                            id=row["id"],
                            name=row["name"],
                            path_lower=row["path_lower"],
                            path_display=row["path_display"],
                            size=row["size"],
                            modified=datetime.fromisoformat(row["modified_date"]),
                            content_hash=row["content_hash"],
                            is_downloadable=bool(row["is_downloadable"]),
                            file_type=row["file_type"],
                            extension=row["file_extension"]
                        )
                        files.append(file)
                    except Exception as e:
                        logger.warning(f"Error converting cached row to DropboxFile: {e}")
                        continue
                
                logger.info(f"Retrieved {len(files)} files from cache")
                return files
                
        except Exception as e:
            logger.error(f"Error getting files from cache: {e}")
            return []
    
    def get_file_by_path(self, path: str) -> Optional[DropboxFile]:
        """Get a specific file by path from cache"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM files 
                    WHERE path_lower = ? OR path_display = ?
                    LIMIT 1
                """, (path.lower(), path))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                return DropboxFile(
                    id=row["id"],
                    name=row["name"],
                    path_lower=row["path_lower"],
                    path_display=row["path_display"],
                    size=row["size"],
                    modified=datetime.fromisoformat(row["modified_date"]),
                    content_hash=row["content_hash"],
                    is_downloadable=bool(row["is_downloadable"]),
                    file_type=row["file_type"],
                    extension=row["file_extension"]
                )
                
        except Exception as e:
            logger.error(f"Error getting file by path from cache: {e}")
            return None
    
    def get_files_modified_after(self, after_date: datetime) -> List[DropboxFile]:
        """Get files modified after a specific date from cache"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM files 
                    WHERE is_folder = 0 AND modified_date > ?
                    ORDER BY modified_date DESC
                """, (after_date.isoformat(),))
                
                rows = cursor.fetchall()
                
                files = []
                for row in rows:
                    try:
                        file = DropboxFile(
                            id=row["id"],
                            name=row["name"],
                            path_lower=row["path_lower"],
                            path_display=row["path_display"],
                            size=row["size"],
                            modified=datetime.fromisoformat(row["modified_date"]),
                            content_hash=row["content_hash"],
                            is_downloadable=bool(row["is_downloadable"]),
                            file_type=row["file_type"],
                            extension=row["file_extension"]
                        )
                        files.append(file)
                    except Exception as e:
                        logger.warning(f"Error converting cached row: {e}")
                        continue
                
                logger.info(f"Found {len(files)} files modified after {after_date}")
                return files
                
        except Exception as e:
            logger.error(f"Error getting modified files from cache: {e}")
            return []
    
    def remove_file(self, path: str) -> bool:
        """Remove a file from cache (for deletions)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM files 
                    WHERE path_lower = ? OR path_display = ?
                """, (path.lower(), path))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.info(f"Removed file from cache: {path}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Error removing file from cache: {e}")
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the local cache"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Total files
                cursor.execute("SELECT COUNT(*) FROM files WHERE is_folder = 0")
                total_files = cursor.fetchone()[0]
                
                # Files by type
                cursor.execute("""
                    SELECT file_type, COUNT(*) 
                    FROM files 
                    WHERE is_folder = 0 
                    GROUP BY file_type
                """)
                by_type = dict(cursor.fetchall())
                
                # Last sync info
                cursor.execute("""
                    SELECT key, value 
                    FROM sync_metadata 
                    WHERE key IN ('last_sync', 'last_full_sync')
                """)
                sync_info = dict(cursor.fetchall())
                
                # Database size
                db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                
                return {
                    "total_files": total_files,
                    "by_type": by_type,
                    "last_sync": sync_info.get("last_sync"),
                    "last_full_sync": sync_info.get("last_full_sync"),
                    "database_size_bytes": db_size,
                    "database_size_mb": round(db_size / (1024 * 1024), 2)
                }
                
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {
                "total_files": 0,
                "by_type": {},
                "error": str(e)
            }
    
    def clear_cache(self) -> bool:
        """Clear all cached data (use with caution)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM files")
                conn.execute("DELETE FROM sync_metadata")
                conn.commit()
                
            logger.info("Cache cleared successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False
    
    def is_cache_empty(self) -> bool:
        """Check if cache is empty (needs initial sync)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM files")
                count = cursor.fetchone()[0]
                return count == 0
                
        except Exception as e:
            logger.error(f"Error checking if cache is empty: {e}")
            return True 