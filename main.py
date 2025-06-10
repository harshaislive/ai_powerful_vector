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

@app.post("/api/process/all")
async def process_all_files(background_tasks: BackgroundTasks):
    """Start processing all files in Dropbox"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if already processing
    current_status = processing_service.get_processing_status()
    if current_status.status == "running":
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    # Start processing in background
    background_tasks.add_task(process_all_background)
    
    return {"message": "Processing started", "status": "initiated"}

@app.post("/api/process/new")
async def process_new_files(background_tasks: BackgroundTasks, hours_back: int = 24):
    """Start processing files modified in the last N hours"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if already processing
    current_status = processing_service.get_processing_status()
    if current_status.status == "running":
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    # Start processing in background
    background_tasks.add_task(process_new_background, hours_back)
    
    return {"message": f"Processing files from last {hours_back} hours", "status": "initiated"}

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

# Background task functions

async def process_all_background():
    """Background task to process all files"""
    try:
        await processing_service.process_all_files()
    except Exception as e:
        logger.error(f"Error in background processing: {e}")

async def process_new_background(hours_back: int):
    """Background task to process new files"""
    try:
        cutoff_date = datetime.now() - timedelta(hours=hours_back)
        await processing_service.process_new_files(cutoff_date)
    except Exception as e:
        logger.error(f"Error in background processing: {e}")

# Error handlers

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"Internal server error: {exc}")
    return templates.TemplateResponse("500.html", {"request": request, "error": str(exc)}, status_code=500)

# Railway will start the app directly, no need for if __name__ == "__main__" 