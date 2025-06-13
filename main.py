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
    startup_errors = []
    try:
        # Run Railway-specific startup checks
        try:
            from railway_startup import main as railway_startup
            railway_startup()
        except ImportError:
            logger.info("Railway startup script not found - continuing with standard startup")
        except Exception as e:
            logger.warning(f"Railway startup script failed: {e} - continuing anyway")
        
        logger.info("Starting up Dropbox Vector Search Engine...")
        
        # Initialize processing service with error handling
        try:
            processing_service = ProcessingService()
            logger.info("✅ Processing service initialized successfully")
        except Exception as e:
            error_msg = f"❌ Failed to initialize ProcessingService: {str(e)}"
            logger.error(error_msg)
            startup_errors.append(error_msg)
            processing_service = None
        
        # Initialize scheduler (independent of processing service)
        try:
            scheduler = AsyncIOScheduler()
            
            # Only add jobs if processing service is available
            if processing_service:
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
                
                logger.info(f"✅ Scheduled daily processing at {config.CRON_HOUR:02d}:{config.CRON_MINUTE:02d}")
            else:
                logger.warning("⚠️ Skipping scheduled jobs - ProcessingService not available")
            
            scheduler.start()
            logger.info("✅ Scheduler initialized successfully")
            
        except Exception as e:
            error_msg = f"❌ Failed to initialize scheduler: {str(e)}"
            logger.error(error_msg)
            startup_errors.append(error_msg)
            scheduler = None
        
        # Log startup summary
        if startup_errors:
            logger.warning(f"🔥 Startup completed with {len(startup_errors)} errors:")
            for error in startup_errors:
                logger.warning(f"   • {error}")
            logger.warning("📱 App will run in degraded mode - some features may not work")
        else:
            logger.info("🎉 Startup completed successfully - all services running")
        
    except Exception as e:
        logger.error(f"💥 Critical error during startup: {e}")
        # Don't raise - let the app start anyway for health checks
    
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
    """Health check endpoint - Railway compatible"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "app": "running",
                "processing": processing_service is not None,
                "scheduler": scheduler is not None and scheduler.running if scheduler else False
            }
        }
        
        # Basic service checks without failing the health check
        if processing_service:
            try:
                # Test basic service availability
                health_status["services"]["dropbox"] = hasattr(processing_service, 'dropbox_service') and processing_service.dropbox_service is not None
                health_status["services"]["replicate"] = hasattr(processing_service, 'replicate_service') and processing_service.replicate_service is not None
                health_status["services"]["weaviate"] = hasattr(processing_service, 'weaviate_service') and processing_service.weaviate_service is not None
                health_status["services"]["clip"] = hasattr(processing_service, 'clip_service') and processing_service.clip_service is not None
            except Exception as e:
                health_status["services"]["check_error"] = str(e)
        
        return health_status
        
    except Exception as e:
        # Even if there are errors, return 200 OK for Railway health check
        return {
            "status": "degraded",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "services": {
                "app": "running"
            }
        }

@app.get("/api/diagnostics")
async def diagnostics():
    """Detailed diagnostics for debugging Railway deployment"""
    try:
        diagnostics = {
            "timestamp": datetime.now().isoformat(),
            "environment": {
                "port": config.APP_PORT,
                "host": config.APP_HOST,
                "server_url": config.SERVER_URL,
                "railway_domain": os.getenv("RAILWAY_PUBLIC_DOMAIN"),
                "python_path": sys.path[:3],  # First 3 entries only
            },
            "config": {
                "has_dropbox_client_id": bool(config.DROPBOX_CLIENT_ID),
                "has_dropbox_secret": bool(config.DROPBOX_CLIENT_SECRET),
                "has_dropbox_token": bool(config.DROPBOX_REFRESH_TOKEN),
                "has_replicate_token": bool(config.REPLICATE_API_TOKEN),
                "weaviate_url": config.WEAVIATE_URL,
                "has_weaviate_key": bool(config.WEAVIATE_API_KEY and config.WEAVIATE_API_KEY.strip()),
                "clip_service_url": config.CLIP_SERVICE_URL,
            },
            "services": {
                "processing_service": processing_service is not None,
                "scheduler": scheduler is not None and scheduler.running if scheduler else False,
            },
            "errors": []
        }
        
        # Test individual service connections
        if processing_service:
            # Test Dropbox
            try:
                if hasattr(processing_service, 'dropbox_service') and processing_service.dropbox_service:
                    diagnostics["services"]["dropbox"] = "initialized"
                else:
                    diagnostics["services"]["dropbox"] = "not_initialized"
            except Exception as e:
                diagnostics["services"]["dropbox"] = f"error: {str(e)}"
                diagnostics["errors"].append(f"Dropbox: {str(e)}")
            
            # Test Replicate
            try:
                if hasattr(processing_service, 'replicate_service') and processing_service.replicate_service:
                    diagnostics["services"]["replicate"] = "initialized"
                else:
                    diagnostics["services"]["replicate"] = "not_initialized"
            except Exception as e:
                diagnostics["services"]["replicate"] = f"error: {str(e)}"
                diagnostics["errors"].append(f"Replicate: {str(e)}")
            
            # Test Weaviate
            try:
                if hasattr(processing_service, 'weaviate_service') and processing_service.weaviate_service:
                    # Test connection
                    is_ready = processing_service.weaviate_service.client.is_ready()
                    diagnostics["services"]["weaviate"] = f"initialized_ready_{is_ready}"
                else:
                    diagnostics["services"]["weaviate"] = "not_initialized"
            except Exception as e:
                diagnostics["services"]["weaviate"] = f"error: {str(e)}"
                diagnostics["errors"].append(f"Weaviate: {str(e)}")
            
            # Test CLIP
            try:
                if hasattr(processing_service, 'clip_service') and processing_service.clip_service:
                    diagnostics["services"]["clip"] = "initialized"
                else:
                    diagnostics["services"]["clip"] = "not_initialized"
            except Exception as e:
                diagnostics["services"]["clip"] = f"error: {str(e)}"
                diagnostics["errors"].append(f"CLIP: {str(e)}")
        
        return diagnostics
        
    except Exception as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "error": f"Diagnostics failed: {str(e)}",
            "basic_status": "app_running"
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