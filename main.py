from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, Response
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
import dropbox

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
        logger.info("🚀 Starting Dropbox Vector Search Engine...")
        
        # Run Railway-specific startup checks (optional)
        try:
            from railway_startup import main as railway_startup
            railway_startup()
        except ImportError:
            logger.info("Railway startup script not found - continuing with standard startup")
        except Exception as e:
            logger.warning(f"Railway startup script failed: {e} - continuing anyway")
        
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
        
        # Always continue - don't fail startup even if services fail
        logger.info("✅ App is ready to serve requests")
        
    except Exception as e:
        logger.error(f"💥 Critical error during startup: {e}")
        # Don't raise - let the app start anyway for health checks
        logger.info("⚠️ App starting in emergency mode - health checks will work")
    
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
        # Return a simple HTML page if template fails
        return HTMLResponse(f"""
        <html>
            <head><title>Dropbox Vector Search Engine</title></head>
            <body>
                <h1>🚀 Dropbox Vector Search Engine</h1>
                <p>App is starting up... Some services may not be ready yet.</p>
                <p>Error: {str(e)}</p>
                <p><a href="/api/health">Check Health Status</a></p>
                <p><a href="/api/diagnostics">View Diagnostics</a></p>
            </body>
        </html>
        """, status_code=200)

@app.get("/api/health")
async def health_check():
    """Health check endpoint - Railway compatible"""
    # Always return 200 OK for Railway health checks
    # Don't fail health check due to service initialization issues
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "app": "running"
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

@app.get("/api/debug/stats")
async def debug_stats():
    """Debug endpoint to check stats structure"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    stats = processing_service.get_stats()
    
    # Add detailed breakdown for debugging
    debug_info = {
        "stats": stats,
        "cache_by_type_exists": "by_type" in stats.get("local_cache", {}),
        "cache_by_type_value": stats.get("local_cache", {}).get("by_type", "NOT_FOUND"),
        "cache_total_files": stats.get("local_cache", {}).get("total_files", "NOT_FOUND"),
        "template_logic": {
            "image_count": stats.get("local_cache", {}).get("by_type", {}).get("image", 0),
            "video_count": stats.get("local_cache", {}).get("by_type", {}).get("video", 0),
            "should_show_image_button": bool(stats.get("local_cache", {}).get("by_type", {}).get("image", 0) > 0),
            "should_show_video_button": bool(stats.get("local_cache", {}).get("by_type", {}).get("video", 0) > 0),
        }
    }
    
    return debug_info

@app.get("/files/{filename}")
async def serve_file(filename: str):
    """Serve extracted frames and video thumbnails"""
    try:
        # Look for file in temp_files directory
        temp_dir = os.path.join(os.getcwd(), "temp_files")
        file_path = os.path.join(temp_dir, filename)
        
        if os.path.exists(file_path):
            return FileResponse(
                file_path,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=3600"}
            )
        else:
            raise HTTPException(status_code=404, detail="File not found")
            
    except Exception as e:
        logger.error(f"Error serving file {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/image/{file_id}")
async def get_image_from_dropbox(file_id: str):
    """Get image directly from Dropbox using file ID from Weaviate"""
    try:
        # Validate UUID format
        import uuid
        try:
            uuid.UUID(file_id)
        except ValueError:
            logger.error(f"Invalid UUID format: {file_id}")
            raise HTTPException(status_code=400, detail="Invalid file ID format")
        
        if not processing_service:
            logger.error("Processing service not initialized")
            raise HTTPException(status_code=503, detail="Processing service not initialized")
        
        if not processing_service.weaviate_service:
            logger.error("Weaviate service not initialized")
            raise HTTPException(status_code=503, detail="Weaviate service not initialized")
        
        logger.info(f"Getting image for file ID: {file_id}")
        
        # Get file info from Weaviate using file ID
        file_data = processing_service.weaviate_service.get_file_by_id(file_id)
        if not file_data:
            logger.error(f"File not found in Weaviate: {file_id}")
            raise HTTPException(status_code=404, detail="File not found in database")
        
        dropbox_path = file_data.get("dropbox_path")
        if not dropbox_path:
            logger.error(f"No dropbox_path found for file: {file_id}")
            raise HTTPException(status_code=404, detail="File path not found")
        
        logger.info(f"Downloading file from Dropbox: {dropbox_path}")
        
        # Download file content directly from Dropbox
        try:
            metadata, response = processing_service.dropbox_service.dbx.files_download(dropbox_path)
            
            # Determine content type based on file extension
            content_type = "image/jpeg"  # Default
            if dropbox_path.lower().endswith(('.png',)):
                content_type = "image/png"
            elif dropbox_path.lower().endswith(('.gif',)):
                content_type = "image/gif"
            elif dropbox_path.lower().endswith(('.webp',)):
                content_type = "image/webp"
            elif dropbox_path.lower().endswith(('.bmp',)):
                content_type = "image/bmp"
            
            logger.info(f"Successfully downloaded file: {dropbox_path}, size: {len(response.content)} bytes")
            
            return Response(
                content=response.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Content-Disposition": f'inline; filename="{metadata.name}"'
                }
            )
            
        except dropbox.exceptions.ApiError as e:
            logger.error(f"Dropbox API error for {dropbox_path}: {e}")
            raise HTTPException(status_code=404, detail="File not found in Dropbox")
        except Exception as e:
            logger.error(f"Unexpected error downloading {dropbox_path}: {e}")
            raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving image {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/thumbnail/{file_id}")
async def get_thumbnail_from_dropbox(file_id: str, size: str = "medium"):
    """Get thumbnail directly from Dropbox using file ID from Weaviate"""
    try:
        # Validate UUID format
        import uuid
        try:
            uuid.UUID(file_id)
        except ValueError:
            logger.error(f"Invalid UUID format: {file_id}")
            raise HTTPException(status_code=400, detail="Invalid file ID format")
        
        if not processing_service:
            logger.error("Processing service not initialized")
            raise HTTPException(status_code=503, detail="Processing service not initialized")
        
        if not processing_service.weaviate_service:
            logger.error("Weaviate service not initialized")
            raise HTTPException(status_code=503, detail="Weaviate service not initialized")
        
        logger.info(f"Getting thumbnail for file ID: {file_id}, size: {size}")
        
        # Get file info from Weaviate using file ID
        file_data = processing_service.weaviate_service.get_file_by_id(file_id)
        if not file_data:
            logger.error(f"File not found in Weaviate: {file_id}")
            raise HTTPException(status_code=404, detail="File not found in database")
        
        dropbox_path = file_data.get("dropbox_path")
        file_type = file_data.get("file_type", "")
        
        if not dropbox_path:
            logger.error(f"No dropbox_path found for file: {file_id}")
            raise HTTPException(status_code=404, detail="File path not found")
        
        logger.info(f"Getting thumbnail for: {dropbox_path}, type: {file_type}")
        
        # For videos, try to get thumbnail or return placeholder
        if file_type == "video":
            try:
                # Try to get video thumbnail from Dropbox
                metadata, thumbnail_content = processing_service.dropbox_service.dbx.files_get_thumbnail(
                    dropbox_path,
                    format=dropbox.files.ThumbnailFormat.jpeg,
                    size=dropbox.files.ThumbnailSize.w640h480
                )
                logger.info(f"Successfully got video thumbnail: {dropbox_path}")
                return Response(
                    content=thumbnail_content,
                    media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=3600"}
                )
            except Exception as e:
                # Video thumbnail not available, fall back to full image endpoint
                logger.warning(f"No thumbnail available for video {dropbox_path}: {e}")
                return await get_image_from_dropbox(file_id)
        
        # For images, get thumbnail from Dropbox
        try:
            # Map size parameter to Dropbox thumbnail sizes
            size_mapping = {
                "small": dropbox.files.ThumbnailSize.w128h128,
                "medium": dropbox.files.ThumbnailSize.w640h480,
                "large": dropbox.files.ThumbnailSize.w1024h768
            }
            
            thumbnail_size = size_mapping.get(size, dropbox.files.ThumbnailSize.w640h480)
            
            # Get thumbnail from Dropbox
            metadata, thumbnail_content = processing_service.dropbox_service.dbx.files_get_thumbnail(
                dropbox_path,
                format=dropbox.files.ThumbnailFormat.jpeg,
                size=thumbnail_size
            )
            
            logger.info(f"Successfully got thumbnail: {dropbox_path}, size: {len(thumbnail_content)} bytes")
            
            return Response(
                content=thumbnail_content,
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Content-Disposition": f'inline; filename="thumb_{metadata.name}.jpg"'
                }
            )
            
        except dropbox.exceptions.ApiError as e:
            logger.warning(f"Thumbnail not available for {dropbox_path}: {e}, falling back to full image")
            # Fallback to full image if thumbnail fails
            return await get_image_from_dropbox(file_id)
        except Exception as e:
            logger.error(f"Error getting thumbnail for {dropbox_path}: {e}")
            # Fallback to full image if thumbnail fails
            return await get_image_from_dropbox(file_id)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving thumbnail {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/file/{file_id}")
async def get_file_from_dropbox(file_id: str):
    """Get any file directly from Dropbox using file ID from Weaviate"""
    try:
        if not processing_service:
            raise HTTPException(status_code=503, detail="Processing service not initialized")
        
        # Get file info from Weaviate using file ID
        file_data = processing_service.weaviate_service.get_file_by_id(file_id)
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found in database")
        
        dropbox_path = file_data.get("dropbox_path")
        file_type = file_data.get("file_type", "")
        
        if not dropbox_path:
            raise HTTPException(status_code=404, detail="File path not found")
        
        # Download file content directly from Dropbox
        try:
            metadata, response = processing_service.dropbox_service.dbx.files_download(dropbox_path)
            
            # Determine content type based on file type and extension
            content_type = "application/octet-stream"  # Default
            
            if file_type == "image":
                if dropbox_path.lower().endswith(('.jpg', '.jpeg')):
                    content_type = "image/jpeg"
                elif dropbox_path.lower().endswith(('.png',)):
                    content_type = "image/png"
                elif dropbox_path.lower().endswith(('.gif',)):
                    content_type = "image/gif"
                elif dropbox_path.lower().endswith(('.webp',)):
                    content_type = "image/webp"
                elif dropbox_path.lower().endswith(('.bmp',)):
                    content_type = "image/bmp"
            elif file_type == "video":
                if dropbox_path.lower().endswith(('.mp4',)):
                    content_type = "video/mp4"
                elif dropbox_path.lower().endswith(('.avi',)):
                    content_type = "video/x-msvideo"
                elif dropbox_path.lower().endswith(('.mov',)):
                    content_type = "video/quicktime"
                elif dropbox_path.lower().endswith(('.mkv',)):
                    content_type = "video/x-matroska"
                elif dropbox_path.lower().endswith(('.wmv',)):
                    content_type = "video/x-ms-wmv"
                elif dropbox_path.lower().endswith(('.flv',)):
                    content_type = "video/x-flv"
            
            return Response(
                content=response.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Content-Disposition": f'inline; filename="{metadata.name}"'
                }
            )
            
        except dropbox.exceptions.ApiError as e:
            logger.error(f"Dropbox API error for {dropbox_path}: {e}")
            raise HTTPException(status_code=404, detail="File not found in Dropbox")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving file {file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/api/debug/cache")
async def debug_cache():
    """Debug endpoint to inspect cache contents"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    try:
        cache_stats = processing_service.dropbox_service.cache.get_cache_stats()
        
        # Get some sample files from cache
        sample_files = processing_service.dropbox_service.cache.get_files()[:5]
        
        return {
            "cache_stats": cache_stats,
            "sample_files": [
                {
                    "name": f.name,
                    "path": f.path_display,
                    "type": f.file_type,
                    "size": f.size,
                    "modified": f.modified.isoformat(),
                    "content_hash": f.content_hash
                } for f in sample_files
            ],
            "recommendations": {
                "cache_health": "healthy" if cache_stats.get("total_files", 0) > 0 else "empty",
                "next_steps": [
                    "Cache looks good, ready for processing" if cache_stats.get("total_files", 0) > 0
                    else "Run 'Sync Cache' to populate cache with Dropbox files"
                ]
            }
        }
    except Exception as e:
        logger.error(f"Error in debug cache: {e}")
        raise HTTPException(status_code=500, detail=f"Error debugging cache: {e}")

@app.get("/api/debug/vectors")
async def debug_vectors():
    """Debug endpoint to validate vector setup and configuration"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    try:
        # Validate vector setup
        vector_validation = processing_service.weaviate_service.validate_vector_setup()
        
        # Get sample vector data if available
        sample_query_result = None
        try:
            sample_query = (
                processing_service.weaviate_service.client.query
                .get("DropboxFile", ["file_name", "file_type", "caption"])
                .with_additional(["vector"])
                .with_limit(2)
                .do()
            )
            sample_files = sample_query.get("data", {}).get("Get", {}).get("DropboxFile", [])
            sample_query_result = []
            for file_data in sample_files:
                vector_data = file_data.get("_additional", {}).get("vector", [])
                sample_query_result.append({
                    "file_name": file_data.get("file_name"),
                    "file_type": file_data.get("file_type"), 
                    "caption": file_data.get("caption", "")[:100] + "..." if file_data.get("caption", "") else None,
                    "has_vector": bool(vector_data),
                    "vector_dimensions": len(vector_data) if vector_data else 0,
                    "vector_sample": vector_data[:5] if vector_data else None  # First 5 dimensions
                })
        except Exception as e:
            sample_query_result = f"Error getting sample data: {str(e)}"
        
        # Test CLIP service
        clip_test = None
        try:
            test_embedding = await processing_service.clip_service.get_text_embedding("test query")
            clip_test = {
                "working": bool(test_embedding),
                "dimensions": len(test_embedding) if test_embedding else 0,
                "sample": test_embedding[:5] if test_embedding else None
            }
        except Exception as e:
            clip_test = {"working": False, "error": str(e)}
        
        return {
            "vector_validation": vector_validation,
            "sample_data": sample_query_result,
            "clip_service": clip_test,
            "summary": {
                "vector_search_ready": vector_validation.get("valid", False) and vector_validation.get("has_sample_vectors", False),
                "critical_issues": [
                    issue for issue in vector_validation.get("issues", [])
                ],
                "next_steps": vector_validation.get("recommendations", [])
            }
        }
    except Exception as e:
        logger.error(f"Error in debug vectors: {e}")
        raise HTTPException(status_code=500, detail=f"Error debugging vectors: {e}")

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

@app.post("/api/process/initial")
async def initial_process_files(background_tasks: BackgroundTasks):
    """Initial processing of all cached files to populate Weaviate (for first-time setup)"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if already processing
    current_status = processing_service.get_processing_status()
    if current_status.status == "running":
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    # Check cache status
    cache_stats = processing_service.dropbox_service.cache.get_cache_stats()
    cached_files = cache_stats.get("total_files", 0)
    
    if cached_files == 0:
        raise HTTPException(status_code=400, detail="No cached files found. Please sync cache first.")
    
    # Start initial processing in background
    background_tasks.add_task(initial_process_background)
    
    return {
        "message": f"Initial processing started for {cached_files} cached files", 
        "status": "initiated",
        "note": "This will process all files from cache to populate Weaviate with embeddings and captions",
        "estimated_time": f"~{cached_files // 60} minutes (depending on file types and API speed)"
    }

@app.post("/api/process/initial/images")
async def initial_process_images(background_tasks: BackgroundTasks):
    """Initial processing of cached images only"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if already processing
    current_status = processing_service.get_processing_status()
    if current_status.status == "running":
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    # Check cache status
    cache_stats = processing_service.dropbox_service.cache.get_cache_stats()
    cached_images = cache_stats.get("by_type", {}).get("image", 0)
    
    if cached_images == 0:
        raise HTTPException(status_code=400, detail="No cached images found. Please sync cache first.")
    
    # Start image processing in background
    background_tasks.add_task(initial_process_images_background)
    
    return {
        "message": f"Initial image processing started for {cached_images} cached images", 
        "status": "initiated",
        "note": "This will process only images from cache with BLIP captions and CLIP embeddings",
        "estimated_time": f"~{cached_images // 60} minutes (images process faster than videos)"
    }

@app.post("/api/process/initial/videos")
async def initial_process_videos(background_tasks: BackgroundTasks):
    """Initial processing of cached videos only"""
    if not processing_service:
        raise HTTPException(status_code=503, detail="Processing service not initialized")
    
    # Check if already processing
    current_status = processing_service.get_processing_status()
    if current_status.status == "running":
        raise HTTPException(status_code=409, detail="Processing already in progress")
    
    # Check cache status
    cache_stats = processing_service.dropbox_service.cache.get_cache_stats()
    cached_videos = cache_stats.get("by_type", {}).get("video", 0)
    
    if cached_videos == 0:
        raise HTTPException(status_code=400, detail="No cached videos found. Please sync cache first.")
    
    # Start video processing in background
    background_tasks.add_task(initial_process_videos_background)
    
    return {
        "message": f"Initial video processing started for {cached_videos} cached videos", 
        "status": "initiated",
        "note": "This will process only videos from cache with AI-generated captions and embeddings",
        "estimated_time": f"~{cached_videos // 30} minutes (videos take longer to process)"
    }

@app.get("/api/download/{file_id}")
async def download_file_from_dropbox(file_id: str):
    """Download file from Dropbox using file ID from Weaviate"""
    try:
        if not processing_service:
            raise HTTPException(status_code=503, detail="Processing service not initialized")
        
        # Get file info from Weaviate using file ID
        file_data = processing_service.weaviate_service.get_file_by_id(file_id)
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found in database")
        
        dropbox_path = file_data.get("dropbox_path")
        file_name = file_data.get("file_name", "download")
        
        if not dropbox_path:
            raise HTTPException(status_code=404, detail="File path not found")
        
        # Download file content directly from Dropbox
        try:
            metadata, response = processing_service.dropbox_service.dbx.files_download(dropbox_path)
            
            return Response(
                content=response.content,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": f'attachment; filename="{file_name}"',
                    "Content-Length": str(len(response.content))
                }
            )
            
        except dropbox.exceptions.ApiError as e:
            logger.error(f"Dropbox API error for download {dropbox_path}: {e}")
            raise HTTPException(status_code=404, detail="File not found in Dropbox")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading file {file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/debug/file/{file_id}")
async def debug_file_by_id(file_id: str):
    """Debug endpoint to test file retrieval from Weaviate with complete data including vectors"""
    try:
        # Validate UUID format
        import uuid
        try:
            uuid.UUID(file_id)
        except ValueError:
            return {"error": "Invalid UUID format", "file_id": file_id}
        
        if not processing_service:
            return {"error": "Processing service not initialized"}
        
        if not processing_service.weaviate_service:
            return {"error": "Weaviate service not initialized"}
        
        # Query Weaviate directly with vector data
        query = (
            processing_service.weaviate_service.client.query
            .get("DropboxFile", [
                "dropbox_path", "file_name", "file_type", "file_extension", 
                "file_size", "caption", "tags", "modified_date", "processed_date",
                "content_hash", "public_url", "thumbnail_url"
            ])
            .with_additional(["id", "vector"])
            .with_where({
                "path": ["id"],
                "operator": "Equal",
                "valueText": file_id
            })
            .do()
        )
        
        files = query.get("data", {}).get("Get", {}).get("DropboxFile", [])
        
        if not files:
            return {
                "error": "File not found in Weaviate",
                "file_id": file_id,
                "weaviate_connected": processing_service.weaviate_service.client.is_ready()
            }
        
        file_data = files[0]
        additional = file_data.get("_additional", {})
        vector_data = additional.get("vector", [])
        
        return {
            "success": True,
            "file_id": file_id,
            "file_data": {
                "dropbox_path": file_data.get("dropbox_path", ""),
                "file_name": file_data.get("file_name", ""),
                "file_type": file_data.get("file_type", ""),
                "file_extension": file_data.get("file_extension", ""),
                "file_size": file_data.get("file_size", 0),
                "caption": file_data.get("caption", ""),
                "tags": file_data.get("tags", []),
                "modified_date": file_data.get("modified_date", ""),
                "processed_date": file_data.get("processed_date", ""),
                "content_hash": file_data.get("content_hash", ""),
                "public_url": file_data.get("public_url", ""),
                "thumbnail_url": file_data.get("thumbnail_url", ""),
                "has_vector": bool(vector_data and len(vector_data) > 0),
                "vector_dimensions": len(vector_data) if vector_data else 0,
                "vector_sample": vector_data[:10] if vector_data else [],
                "vector_stats": {
                    "min": min(vector_data) if vector_data else None,
                    "max": max(vector_data) if vector_data else None,
                    "mean": sum(vector_data) / len(vector_data) if vector_data else None
                } if vector_data else None
            }
        }
        
    except Exception as e:
        logger.error(f"Debug file retrieval error: {e}", exc_info=True)
        return {"error": str(e), "file_id": file_id}

@app.get("/data", response_class=HTMLResponse)
async def data_viewer_page(request: Request):
    """Data viewer page to see all Weaviate data in table format"""
    return templates.TemplateResponse("data_viewer.html", {"request": request})

@app.get("/api/data/all")
async def get_all_data(page: int = 1, limit: int = 50):
    """Get all data from Weaviate with pagination"""
    try:
        if not processing_service or not processing_service.weaviate_service:
            raise HTTPException(status_code=503, detail="Weaviate service not available")
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Query all files with pagination
        query = (
            processing_service.weaviate_service.client.query
            .get("DropboxFile", [
                "dropbox_path", "file_name", "file_type", "file_extension", 
                "file_size", "caption", "tags", "modified_date", "processed_date",
                "content_hash", "public_url", "thumbnail_url"
            ])
            .with_additional(["id", "vector"])
            .with_limit(limit)
            .with_offset(offset)
            .do()
        )
        
        files = query.get("data", {}).get("Get", {}).get("DropboxFile", [])
        
        # Get total count
        total_query = (
            processing_service.weaviate_service.client.query
            .aggregate("DropboxFile")
            .with_meta_count()
            .do()
        )
        total_count = total_query.get("data", {}).get("Aggregate", {}).get("DropboxFile", [{}])[0].get("meta", {}).get("count", 0)
        
        # Format the data
        formatted_files = []
        for file_data in files:
            additional = file_data.get("_additional", {})
            vector_data = additional.get("vector", [])
            
            formatted_file = {
                "id": additional.get("id", ""),
                "dropbox_path": file_data.get("dropbox_path", ""),
                "file_name": file_data.get("file_name", ""),
                "file_type": file_data.get("file_type", ""),
                "file_extension": file_data.get("file_extension", ""),
                "file_size": file_data.get("file_size", 0),
                "caption": file_data.get("caption", ""),
                "tags": file_data.get("tags", []),
                "modified_date": file_data.get("modified_date", ""),
                "processed_date": file_data.get("processed_date", ""),
                "content_hash": file_data.get("content_hash", ""),
                "has_vector": bool(vector_data and len(vector_data) > 0),
                "vector_dimensions": len(vector_data) if vector_data else 0,
                "vector_sample": vector_data[:5] if vector_data else [],
                "public_url": file_data.get("public_url", ""),
                "thumbnail_url": file_data.get("thumbnail_url", "")
            }
            formatted_files.append(formatted_file)
        
        return {
            "files": formatted_files,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "total_pages": (total_count + limit - 1) // limit,
                "has_next": offset + limit < total_count,
                "has_prev": page > 1
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting all data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/data/stats")
async def get_data_stats():
    """Get detailed statistics about the data"""
    try:
        if not processing_service or not processing_service.weaviate_service:
            raise HTTPException(status_code=503, detail="Weaviate service not available")
        
        # Get total count
        total_query = (
            processing_service.weaviate_service.client.query
            .aggregate("DropboxFile")
            .with_meta_count()
            .do()
        )
        total_count = total_query.get("data", {}).get("Aggregate", {}).get("DropboxFile", [{}])[0].get("meta", {}).get("count", 0)
        
        # Count files with vectors (sample approach for efficiency)
        sample_size = min(1000, total_count)  # Sample up to 1000 files
        vector_query = (
            processing_service.weaviate_service.client.query
            .get("DropboxFile", ["file_name"])
            .with_additional(["vector"])
            .with_limit(sample_size)
            .do()
        )
        
        files = vector_query.get("data", {}).get("Get", {}).get("DropboxFile", [])
        files_with_vectors_sample = 0
        vector_dimensions = 0
        
        for file_data in files:
            vector_data = file_data.get("_additional", {}).get("vector", [])
            if vector_data and len(vector_data) > 0:
                files_with_vectors_sample += 1
                if vector_dimensions == 0:
                    vector_dimensions = len(vector_data)
        
        # Estimate total files with vectors based on sample
        if len(files) > 0:
            vector_ratio = files_with_vectors_sample / len(files)
            files_with_vectors = int(total_count * vector_ratio)
            files_without_vectors = total_count - files_with_vectors
        else:
            files_with_vectors = 0
            files_without_vectors = total_count
        
        # Count by file type
        image_query = (
            processing_service.weaviate_service.client.query
            .aggregate("DropboxFile")
            .with_where({
                "path": ["file_type"],
                "operator": "Equal",
                "valueText": "image"
            })
            .with_meta_count()
            .do()
        )
        
        video_query = (
            processing_service.weaviate_service.client.query
            .aggregate("DropboxFile")
            .with_where({
                "path": ["file_type"],
                "operator": "Equal",
                "valueText": "video"
            })
            .with_meta_count()
            .do()
        )
        
        image_count = image_query.get("data", {}).get("Aggregate", {}).get("DropboxFile", [{}])[0].get("meta", {}).get("count", 0)
        video_count = video_query.get("data", {}).get("Aggregate", {}).get("DropboxFile", [{}])[0].get("meta", {}).get("count", 0)
        
        return {
            "total_files": total_count,
            "files_with_vectors": files_with_vectors,
            "files_without_vectors": files_without_vectors,
            "vector_dimensions": vector_dimensions,
            "file_types": {
                "images": image_count,
                "videos": video_count,
                "other": total_count - image_count - video_count
            },
            "vector_coverage": f"{(files_with_vectors/total_count*100):.1f}%" if total_count > 0 else "0%"
        }
        
    except Exception as e:
        logger.error(f"Error getting data stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        logger.info("Starting smart processing background task")
        await processing_service.smart_process()
        logger.info("Smart processing background task completed")
    except Exception as e:
        logger.error(f"Error in smart processing background task: {e}", exc_info=True)
        # Ensure status is updated on error
        if processing_service:
            processing_service.current_status.status = "failed"
            processing_service.current_status.end_time = datetime.now()
            processing_service.current_status.errors.append(f"Background task error: {str(e)}")

async def process_all_background():
    """Background task for full processing"""
    try:
        logger.info("Starting process all background task")
        await processing_service.process_all_files()
        logger.info("Process all background task completed")
    except Exception as e:
        logger.error(f"Error in processing background task: {e}", exc_info=True)
        # Ensure status is updated on error
        if processing_service:
            processing_service.current_status.status = "failed"
            processing_service.current_status.end_time = datetime.now()
            processing_service.current_status.errors.append(f"Background task error: {str(e)}")

async def process_new_background(hours_back: int):
    """Background task for processing new files"""
    try:
        logger.info(f"Starting process new files background task (last {hours_back} hours)")
        yesterday = datetime.now() - timedelta(hours=hours_back)
        await processing_service.process_new_files(yesterday)
        logger.info("Process new files background task completed")
    except Exception as e:
        logger.error(f"Error in new file processing background task: {e}", exc_info=True)
        # Ensure status is updated on error
        if processing_service:
            processing_service.current_status.status = "failed"
            processing_service.current_status.end_time = datetime.now()
            processing_service.current_status.errors.append(f"Background task error: {str(e)}")

async def initial_process_background():
    """Background task for initial processing of all cached files"""
    try:
        logger.info("Starting initial processing background task")
        await processing_service.process_all_files()
        logger.info("Initial processing background task completed")
    except Exception as e:
        logger.error(f"Error in initial processing background task: {e}", exc_info=True)
        # Ensure status is updated on error
        if processing_service:
            processing_service.current_status.status = "failed"
            processing_service.current_status.end_time = datetime.now()
            processing_service.current_status.errors.append(f"Background task error: {str(e)}")

async def initial_process_images_background():
    """Background task for initial processing of cached images only"""
    try:
        logger.info("Starting initial image processing background task")
        await processing_service.process_images_only()
        logger.info("Initial image processing background task completed")
    except Exception as e:
        logger.error(f"Error in initial image processing background task: {e}", exc_info=True)
        # Ensure status is updated on error
        if processing_service:
            processing_service.current_status.status = "failed"
            processing_service.current_status.end_time = datetime.now()
            processing_service.current_status.errors.append(f"Background task error: {str(e)}")

async def initial_process_videos_background():
    """Background task for initial processing of cached videos only"""
    try:
        logger.info("Starting initial video processing background task")
        await processing_service.process_videos_only()
        logger.info("Initial video processing background task completed")
    except Exception as e:
        logger.error(f"Error in initial video processing background task: {e}", exc_info=True)
        # Ensure status is updated on error
        if processing_service:
            processing_service.current_status.status = "failed"
            processing_service.current_status.end_time = datetime.now()
            processing_service.current_status.errors.append(f"Background task error: {str(e)}")

# Error handlers

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"Internal server error: {exc}")
    return templates.TemplateResponse("500.html", {"request": request, "error": str(exc)}, status_code=500)

# Railway will start the app directly, no need for if __name__ == "__main__" 