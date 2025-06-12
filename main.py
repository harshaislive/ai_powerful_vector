from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
import os
import sys

# Add the current directory to Python path so we can import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config
from models import SearchRequest, SearchResponse, ProcessingStatus
from services.processing_service import ProcessingService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize services
processing_service = None
scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan event handler"""
    global processing_service, scheduler
    
    # Startup
    try:
        logger.info("Starting up Dropbox Vector Search Engine...")
        
        # Initialize processing service
        processing_service = ProcessingService()
        
        # Initialize scheduler for cron jobs
        scheduler = AsyncIOScheduler()
        
        # Schedule daily processing at 10 PM
        scheduler.add_job(
            daily_processing_job,
            CronTrigger(hour=config.CRON_HOUR, minute=config.CRON_MINUTE),
            id="daily_processing",
            name="Daily Dropbox Processing",
            replace_existing=True
        )
        
        # Schedule temp file cleanup every 6 hours
        scheduler.add_job(
            cleanup_temp_files_job,
            CronTrigger(hour="*/6"),  # Every 6 hours
            id="temp_cleanup",
            name="Temp Files Cleanup",
            replace_existing=True
        )
        
        scheduler.start()
        logger.info(f"Scheduled daily processing at {config.CRON_HOUR:02d}:{config.CRON_MINUTE:02d}")
        
        logger.info("Startup completed successfully")
        
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise
    
    yield
    
    # Shutdown
    try:
        logger.info("Shutting down...")
        
        if scheduler:
            scheduler.shutdown()
        
        if processing_service:
            await processing_service.cleanup()
            
        logger.info("Shutdown completed")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

# Initialize FastAPI app
app = FastAPI(
    title="Dropbox Vector Search Engine",
    description="AI-powered search engine for Dropbox images and videos using CLIP embeddings and BLIP captions",
    version="1.0.0",
    lifespan=lifespan
)

# Initialize templates
templates = Jinja2Templates(directory="templates")

# Mount static files (we'll create this later)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount temp files directory for serving downloaded Dropbox files
temp_files_dir = os.path.join(os.getcwd(), "temp_files")
os.makedirs(temp_files_dir, exist_ok=True)
app.mount("/files", StaticFiles(directory=temp_files_dir), name="temp_files")

async def daily_processing_job():
    """Daily job to process new files"""
    try:
        logger.info("Starting daily processing job...")
        
        # Process files modified in the last 24 hours
        yesterday = datetime.now() - timedelta(days=1)
        status = await processing_service.process_new_files(yesterday)
        
        logger.info(f"Daily processing completed. Status: {status.status}, Processed: {status.files_processed}")
        
    except Exception as e:
        logger.error(f"Error in daily processing job: {e}")

async def cleanup_temp_files_job():
    """Job to clean up old temporary files"""
    try:
        logger.info("Starting temp files cleanup job...")
        
        if processing_service and processing_service.dropbox_service:
            processing_service.dropbox_service.cleanup_temp_files(max_age_hours=24)
            
        logger.info("Temp files cleanup completed")
        
    except Exception as e:
        logger.error(f"Error in temp files cleanup job: {e}")

# API Endpoints

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Main dashboard page"""
    try:
        stats = processing_service.get_stats() if processing_service else {}
        status = processing_service.get_processing_status() if processing_service else ProcessingStatus(status="unknown", files_processed=0, files_total=0)
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "stats": stats,
            "status": status
        })
    except Exception as e:
        logger.error(f"Error in root endpoint: {e}")
        return HTMLResponse(f"<h1>Error</h1><p>{str(e)}</p>", status_code=500)

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "processing": processing_service is not None,
            "scheduler": scheduler is not None and scheduler.running
        }
    }

@app.get("/api/stats")
async def get_stats():
    """Get system statistics"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    return processing_service.get_stats()

@app.get("/api/status")
async def get_processing_status():
    """Get current processing status"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    return processing_service.get_processing_status()

@app.post("/api/cache/sync")
async def sync_cache(background_tasks: BackgroundTasks):
    """Sync local cache with Dropbox (recommended before processing)"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Start cache sync in background
    background_tasks.add_task(sync_cache_background)
    
    return {
        "message": "Cache sync started", 
        "status": "initiated",
        "note": "This will update the local file cache from Dropbox. Much faster than full processing!"
    }

@app.get("/api/cache/stats")
async def get_cache_stats():
    """Get local cache statistics"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    try:
        stats = processing_service.dropbox_service.cache.get_cache_stats()
        return {"status": "success", "cache_stats": stats}
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting cache stats: {e}")

@app.delete("/api/cache/clear")
async def clear_cache():
    """Clear local cache (use with caution)"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    try:
        success = processing_service.dropbox_service.cache.clear_cache()
        if success:
            return {"message": "Cache cleared successfully", "status": "success"}
        else:
            raise HTTPException(status_code=500, detail="Failed to clear cache")
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {e}")

@app.post("/api/process/smart")
async def smart_process_files(background_tasks: BackgroundTasks):
    """Start smart incremental processing (recommended) - only processes changed files"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if already processing
    current_status = processing_service.get_processing_status()
    if current_status.status == "running":
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    # Check if cache is empty
    cache_empty = processing_service.dropbox_service.cache.is_cache_empty() if processing_service else True
    
    # Start smart processing in background
    background_tasks.add_task(smart_process_background)
    
    response = {
        "message": "Smart processing started", 
        "status": "initiated", 
        "note": "Only processing files that have changed since last sync"
    }
    
    if cache_empty:
        response["warning"] = "Cache is empty - this will do a full sync first, then process changes"
    
    return response

@app.post("/api/process/all")
async def process_all_files(background_tasks: BackgroundTasks):
    """Start full processing of all files (uses local cache when available)"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if already processing
    current_status = processing_service.get_processing_status()
    if current_status.status == "running":
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    # Check cache status
    cache_empty = processing_service.dropbox_service.cache.is_cache_empty() if processing_service else True
    
    # Start full processing in background
    background_tasks.add_task(process_all_background)
    
    response = {
        "message": "Full processing started", 
        "status": "initiated"
    }
    
    if cache_empty:
        response["note"] = "Cache is empty - will fetch files from Dropbox first, then process all files. This may take a while."
        response["recommendation"] = "For faster processing, use 'Sync Cache' first, then 'Smart Process'"
    else:
        response["note"] = "Processing all files from local cache. This may take a while depending on file count."
    
    return response

@app.post("/api/process/new")
async def process_new_files(background_tasks: BackgroundTasks, hours_back: int = 24):
    """Start processing new files (last N hours) - DEPRECATED: Use /api/process/smart instead"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if already processing
    current_status = processing_service.get_processing_status()
    if current_status.status == "running":
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    # Start processing in background
    background_tasks.add_task(process_new_background, hours_back)
    
    return {
        "message": f"Processing files from last {hours_back} hours", 
        "status": "initiated",
        "deprecation_warning": "This endpoint is deprecated. Use /api/process/smart for better efficiency."
    }

@app.post("/api/process/pause")
async def pause_processing():
    """Pause the current processing"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    success = await processing_service.pause_processing()
    if success:
        return {"message": "Processing paused", "status": "paused"}
    else:
        raise HTTPException(status_code=400, detail="No active processing to pause")

@app.post("/api/process/resume")
async def resume_processing():
    """Resume the paused processing"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    success = await processing_service.resume_processing()
    if success:
        return {"message": "Processing resumed", "status": "running"}
    else:
        raise HTTPException(status_code=400, detail="No paused processing to resume")

@app.post("/api/process/stop")
async def stop_processing():
    """Stop the current processing"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    success = await processing_service.stop_processing()
    if success:
        return {"message": "Processing stopped", "status": "stopped"}
    else:
        raise HTTPException(status_code=400, detail="No active processing to stop")

@app.post("/api/search")
async def search_files(search_request: SearchRequest):
    """Search files using vector similarity and text search"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    try:
        start_time = datetime.now()
        
        results = await processing_service.search_files(
            query=search_request.query,
            limit=search_request.limit,
            file_types=search_request.file_types
        )
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Convert results to SearchResult format
        search_results = []
        for item in results:
            result = item["result"]
            search_results.append(result)
        
        return SearchResponse(
            results=search_results,
            total_count=len(search_results),
            query=search_request.query,
            processing_time=processing_time
        )
        
    except Exception as e:
        logger.error(f"Error in search: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/search")
async def search_files_get(q: str, limit: int = 10, file_types: Optional[str] = None):
    """GET version of search for simple queries"""
    file_types_list = file_types.split(",") if file_types else None
    
    search_request = SearchRequest(
        query=q,
        limit=limit,
        file_types=file_types_list
    )
    
    return await search_files(search_request)

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    """Search page UI"""
    return templates.TemplateResponse("search.html", {"request": request})

@app.post("/api/cache/init")
async def initialize_cache(background_tasks: BackgroundTasks):
    """Initialize cache with full Dropbox sync (for first-time setup)"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if cache is already populated
    cache_stats = processing_service.dropbox_service.cache.get_cache_stats()
    if cache_stats.get("total_files", 0) > 0:
        return {
            "message": "Cache already initialized",
            "status": "already_populated",
            "files_cached": cache_stats.get("total_files", 0),
            "note": "Use 'Sync Cache' to update with latest changes"
        }
    
    # Start cache initialization in background
    background_tasks.add_task(init_cache_background)
    
    return {
        "message": "Cache initialization started", 
        "status": "initiated",
        "note": "This will fetch all files from Dropbox and populate the local cache. Check status for progress."
    }

@app.get("/api/cache/progress")
async def get_cache_progress():
    """Get cache sync progress (for live updates)"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    try:
        stats = processing_service.dropbox_service.cache.get_cache_stats()
        
        # Check if any processing is running
        processing_status = processing_service.get_processing_status() if processing_service else None
        
        return {
            "cache_stats": stats,
            "processing_status": {
                "status": processing_status.status if processing_status else "idle",
                "files_processed": processing_status.files_processed if processing_status else 0,
                "files_total": processing_status.files_total if processing_status else 0,
                "current_file": processing_status.current_file if processing_status else None
            } if processing_status else {"status": "idle"},
            "recommendations": {
                "cache_empty": stats.get("total_files", 0) == 0,
                "next_action": "Initialize Cache" if stats.get("total_files", 0) == 0 else "Smart Process"
            }
        }
    except Exception as e:
        logger.error(f"Error getting cache progress: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting progress: {e}")

# Background task functions

async def init_cache_background():
    """Background task for initializing cache with full Dropbox sync"""
    try:
        logger.info("Starting cache initialization background task")
        changed_files, cursor = processing_service.dropbox_service.get_incremental_changes()
        logger.info(f"Cache initialization completed: {len(changed_files)} files cached")
    except Exception as e:
        logger.error(f"Error in cache initialization background task: {e}")

async def sync_cache_background():
    """Background task for syncing local cache with Dropbox"""
    try:
        logger.info("Starting cache sync background task")
        changed_files, cursor = processing_service.dropbox_service.get_incremental_changes()
        logger.info(f"Cache sync completed: {len(changed_files)} files updated")
    except Exception as e:
        logger.error(f"Error in cache sync background task: {e}")

async def smart_process_background():
    """Background task for smart incremental processing"""
    try:
        await processing_service.smart_process()
    except Exception as e:
        logger.error(f"Error in smart processing background task: {e}")

async def process_all_background():
    """Background task for full processing"""
    try:
        await processing_service.process_all_files()
    except Exception as e:
        logger.error(f"Error in processing background task: {e}")

async def process_new_background(hours_back: int):
    """Background task for processing new files"""
    try:
        yesterday = datetime.now() - timedelta(hours=hours_back)
        await processing_service.process_new_files(yesterday)
    except Exception as e:
        logger.error(f"Error in new file processing background task: {e}")

# Error handlers

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"Internal server error: {exc}")
    return templates.TemplateResponse("500.html", {"request": request, "error": str(exc)}, status_code=500)

# Railway will start the app directly, no need for if __name__ == "__main__" 