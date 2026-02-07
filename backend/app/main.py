from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
from typing import Optional, List
import logging
import os
from dotenv import load_dotenv
from db import DatabaseManager
import json
from threading import Lock
from transcript_processor import TranscriptProcessor
import time

# Load environment variables
load_dotenv()

# Configure logger with line numbers and function names
logger = logging.getLogger(__name__)
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger.setLevel(getattr(logging, log_level, logging.INFO))

# Create console handler with formatting
console_handler = logging.StreamHandler()
console_handler.setLevel(getattr(logging, log_level, logging.INFO))

# Create formatter with line numbers and function names
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d - %(funcName)s()] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
console_handler.setFormatter(formatter)

# Add handler to logger if not already added
if not logger.handlers:
    logger.addHandler(console_handler)

app = FastAPI(
    title="Uchitil Live Session API",
    description="API for processing and summarizing tutoring session transcripts",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3118",
        "http://127.0.0.1:3118",
        "tauri://localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Global database manager instance for session management endpoints
db = DatabaseManager()


# Pydantic models for session management
class Transcript(BaseModel):
    id: str
    text: str
    timestamp: str
    # Recording-relative timestamps for audio-transcript synchronization
    audio_start_time: Optional[float] = None
    audio_end_time: Optional[float] = None
    duration: Optional[float] = None


class SessionResponse(BaseModel):
    id: str
    title: str


class SessionDetailsResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    transcripts: List[Transcript]


class SessionTitleUpdate(BaseModel):
    session_id: str
    title: str


class DeleteSessionRequest(BaseModel):
    session_id: str


class SaveTranscriptRequest(BaseModel):
    session_title: str
    transcripts: List[Transcript]
    folder_path: Optional[str] = (
        None  # Path to session folder (for new folder structure)
    )


class SaveModelConfigRequest(BaseModel):
    provider: str
    model: str
    whisperModel: str
    apiKey: Optional[str] = None


class SaveTranscriptConfigRequest(BaseModel):
    provider: str
    model: str
    apiKey: Optional[str] = None


class TranscriptRequest(BaseModel):
    """Request model for transcript text, updated with session_id"""

    text: str
    model: str
    model_name: str
    session_id: str
    chunk_size: Optional[int] = 5000
    overlap: Optional[int] = 1000
    custom_prompt: Optional[str] = "Generate a summary of the session transcript."


class SummaryProcessor:
    """Handles the processing of summaries in a thread-safe way"""

    def __init__(self):
        try:
            self.db = DatabaseManager()

            logger.info("Initializing SummaryProcessor components")
            self.transcript_processor = TranscriptProcessor()
            logger.info("SummaryProcessor initialized successfully (core components)")
        except Exception as e:
            logger.error(
                f"Failed to initialize SummaryProcessor: {str(e)}", exc_info=True
            )
            raise

    async def initialize_db(self):
        """Initialize the database connection (must be called at startup)"""
        await self.db.initialize()

    async def process_transcript(
        self,
        text: str,
        model: str,
        model_name: str,
        chunk_size: int = 5000,
        overlap: int = 1000,
        custom_prompt: str = "Generate a summary of the session transcript.",
    ) -> tuple:
        """Process a transcript text"""
        try:
            if not text:
                raise ValueError("Empty transcript text provided")

            # Validate chunk_size and overlap
            if chunk_size <= 0:
                raise ValueError("chunk_size must be positive")
            if overlap < 0:
                raise ValueError("overlap must be non-negative")
            if overlap >= chunk_size:
                overlap = chunk_size - 1  # Ensure overlap is less than chunk_size

            # Ensure step size is positive
            step_size = chunk_size - overlap
            if step_size <= 0:
                chunk_size = overlap + 1  # Adjust chunk_size to ensure positive step

            logger.info(
                f"Processing transcript of length {len(text)} with chunk_size={chunk_size}, overlap={overlap}"
            )
            (
                num_chunks,
                all_json_data,
            ) = await self.transcript_processor.process_transcript(
                text=text,
                model=model,
                model_name=model_name,
                chunk_size=chunk_size,
                overlap=overlap,
                custom_prompt=custom_prompt,
            )
            logger.info(f"Successfully processed transcript into {num_chunks} chunks")

            return num_chunks, all_json_data
        except Exception as e:
            logger.error(f"Error processing transcript: {str(e)}", exc_info=True)
            raise

    def cleanup(self):
        """Cleanup resources"""
        try:
            logger.info("Cleaning up resources")
            if hasattr(self, "transcript_processor"):
                self.transcript_processor.cleanup()
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)


# Initialize processor
processor = SummaryProcessor()


@app.on_event("startup")
async def startup_event():
    """Initialize database connections at startup"""
    logger.info("Starting Uchitil Live Session API...")
    await db.initialize()
    await processor.initialize_db()
    logger.info("Database connections initialized successfully")


# Session management endpoints
@app.get("/get-sessions", response_model=List[SessionResponse])
async def get_sessions():
    """Get all sessions with their basic information"""
    try:
        sessions = await db.get_all_sessions()
        return [
            {"id": session["id"], "title": session["title"]} for session in sessions
        ]
    except Exception as e:
        logger.error(f"Error getting sessions: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/get-session/{session_id}", response_model=SessionDetailsResponse)
async def get_session(session_id: str):
    """Get a specific session by ID with all its details"""
    try:
        session = await db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/save-session-title")
async def save_session_title(data: SessionTitleUpdate):
    """Save a session title"""
    try:
        await db.update_session_title(data.session_id, data.title)
        return {"message": "Session title saved successfully"}
    except Exception as e:
        logger.error(f"Error saving session title: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/delete-session")
async def delete_session(data: DeleteSessionRequest):
    """Delete a session and all its associated data"""
    try:
        success = await db.delete_session(data.session_id)
        if success:
            return {"message": "Session deleted successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete session")
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def process_transcript_background(
    process_id: str, transcript: TranscriptRequest, custom_prompt: str
):
    """Background task to process transcript"""
    try:
        logger.info(f"Starting background processing for process_id: {process_id}")

        # Early validation for common issues
        if not transcript.text or not transcript.text.strip():
            raise ValueError("Empty transcript text provided")

        if transcript.model in ["claude", "groq", "openai"]:
            # Check if API key is available for cloud providers
            api_key = await processor.db.get_api_key(transcript.model)
            if not api_key:
                provider_names = {
                    "claude": "Anthropic",
                    "groq": "Groq",
                    "openai": "OpenAI",
                }
                raise ValueError(
                    f"{provider_names.get(transcript.model, transcript.model)} API key not configured. Please set your API key in the model settings."
                )

        _, all_json_data = await processor.process_transcript(
            text=transcript.text,
            model=transcript.model,
            model_name=transcript.model_name,
            chunk_size=transcript.chunk_size,
            overlap=transcript.overlap,
            custom_prompt=custom_prompt,
        )

        # Create final summary structure by aggregating chunk results (tutoring-focused)
        final_summary = {
            "SessionName": "",
            "LanguageFocus": "",
            "People": {"title": "People", "blocks": []},
            "VocabularyLearned": {"title": "Vocabulary Learned", "blocks": []},
            "GrammarPoints": {"title": "Grammar Points", "blocks": []},
            "PronunciationNotes": {"title": "Pronunciation Notes", "blocks": []},
            "ConversationTopics": {"title": "Conversation Topics", "blocks": []},
            "CorrectionsMade": {"title": "Corrections Made", "blocks": []},
            "KeyPhrases": {"title": "Key Phrases", "blocks": []},
            "Homework": {"title": "Homework", "blocks": []},
            "ProgressNotes": {"title": "Progress Notes", "blocks": []},
            "SessionNotes": {"session_name": "", "sections": []},
        }

        for json_str in all_json_data:
            try:
                json_dict = json.loads(json_str)

                # Handle SessionName from LLM output
                session_name = json_dict.get("SessionName") or ""
                if session_name:
                    final_summary["SessionName"] = session_name

                # Handle LanguageFocus from LLM output
                language_focus = json_dict.get("LanguageFocus") or ""
                if language_focus:
                    final_summary["LanguageFocus"] = language_focus

                # Handle SessionNotes
                if "SessionNotes" in json_dict:
                    notes = json_dict["SessionNotes"]
                    if isinstance(notes.get("sections"), list):
                        for section in notes["sections"]:
                            if not section.get("blocks"):
                                section["blocks"] = []
                        final_summary["SessionNotes"]["sections"].extend(
                            notes["sections"]
                        )
                    name_field = notes.get("session_name") or ""
                    if name_field:
                        final_summary["SessionNotes"]["session_name"] = name_field

                # Handle tutoring section blocks
                for key in [
                    "People",
                    "VocabularyLearned",
                    "GrammarPoints",
                    "PronunciationNotes",
                    "ConversationTopics",
                    "CorrectionsMade",
                    "KeyPhrases",
                    "Homework",
                    "ProgressNotes",
                ]:
                    if (
                        key in json_dict
                        and isinstance(json_dict[key], dict)
                        and "blocks" in json_dict[key]
                    ):
                        if isinstance(json_dict[key]["blocks"], list):
                            final_summary[key]["blocks"].extend(
                                json_dict[key]["blocks"]
                            )
                            # Also add as a section in SessionNotes if not already present
                            section_exists = False
                            for section in final_summary["SessionNotes"]["sections"]:
                                if section["title"] == json_dict[key]["title"]:
                                    section["blocks"].extend(json_dict[key]["blocks"])
                                    section_exists = True
                                    break

                            if not section_exists:
                                final_summary["SessionNotes"]["sections"].append(
                                    {
                                        "title": json_dict[key]["title"],
                                        "blocks": json_dict[key]["blocks"].copy()
                                        if json_dict[key]["blocks"]
                                        else [],
                                    }
                                )
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse JSON chunk for {process_id}: {e}. Chunk: {json_str[:100]}..."
                )
            except Exception as e:
                logger.error(
                    f"Error processing chunk data for {process_id}: {e}. Chunk: {json_str[:100]}..."
                )

        # Also populate MeetingName/MeetingNotes for backward compatibility with frontend
        final_summary["MeetingName"] = final_summary["SessionName"]
        final_summary["MeetingNotes"] = {
            "meeting_name": final_summary["SessionNotes"]["session_name"],
            "sections": final_summary["SessionNotes"]["sections"],
        }
        # Populate LanguageFocus into SessionNotes for frontend display
        if final_summary["LanguageFocus"]:
            final_summary["SessionNotes"]["language_focus"] = final_summary[
                "LanguageFocus"
            ]

        # Update database with session name using session_id
        if final_summary["SessionName"]:
            await processor.db.update_session_name(
                transcript.session_id, final_summary["SessionName"]
            )

        # Save final result
        if all_json_data:
            await processor.db.update_process(
                process_id, status="completed", result=json.dumps(final_summary)
            )
            logger.info(f"Background processing completed for process_id: {process_id}")
        else:
            error_msg = "Summary generation failed: No chunks were processed successfully. Check logs for specific errors."
            await processor.db.update_process(
                process_id, status="failed", error=error_msg
            )
            logger.error(
                f"Background processing failed for process_id: {process_id} - {error_msg}"
            )

    except ValueError as e:
        # Handle specific value errors (like API key issues)
        error_msg = str(e)
        logger.error(
            f"Configuration error in background processing for {process_id}: {error_msg}",
            exc_info=True,
        )
        try:
            await processor.db.update_process(
                process_id, status="failed", error=error_msg
            )
        except Exception as db_e:
            logger.error(
                f"Failed to update DB status to failed for {process_id}: {db_e}",
                exc_info=True,
            )
    except Exception as e:
        # Handle all other exceptions
        error_msg = f"Processing error: {str(e)}"
        logger.error(
            f"Error in background processing for {process_id}: {error_msg}",
            exc_info=True,
        )
        try:
            await processor.db.update_process(
                process_id, status="failed", error=error_msg
            )
        except Exception as db_e:
            logger.error(
                f"Failed to update DB status to failed for {process_id}: {db_e}",
                exc_info=True,
            )


@app.post("/process-transcript")
async def process_transcript_api(
    transcript: TranscriptRequest, background_tasks: BackgroundTasks
):
    """Process a transcript text with background processing"""
    try:
        # Create new process linked to session_id
        process_id = await processor.db.create_process(transcript.session_id)

        # Save transcript data associated with session_id
        await processor.db.save_transcript(
            transcript.session_id,
            transcript.text,
            transcript.model,
            transcript.model_name,
            transcript.chunk_size,
            transcript.overlap,
        )

        custom_prompt = transcript.custom_prompt

        # Start background processing
        background_tasks.add_task(
            process_transcript_background, process_id, transcript, custom_prompt
        )

        return JSONResponse({"message": "Processing started", "process_id": process_id})

    except Exception as e:
        logger.error(f"Error in process_transcript_api: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/get-summary/{session_id}")
async def get_summary(session_id: str):
    """Get the summary for a given session ID"""
    try:
        result = await processor.db.get_transcript_data(session_id)
        if not result:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "sessionName": None,
                    "meetingName": None,
                    "session_id": session_id,
                    "meeting_id": session_id,
                    "data": None,
                    "start": None,
                    "end": None,
                    "error": "Session ID not found",
                },
            )

        status = result.get("status", "unknown").lower()
        logger.debug(
            f"Summary status for session {session_id}: {status}, error: {result.get('error')}"
        )

        # Parse result data if available
        summary_data = None
        if result.get("result"):
            try:
                parsed_result = json.loads(result["result"])
                if isinstance(parsed_result, str):
                    summary_data = json.loads(parsed_result)
                else:
                    summary_data = parsed_result
                if not isinstance(summary_data, dict):
                    logger.error(
                        f"Parsed summary data is not a dictionary for session {session_id}"
                    )
                    summary_data = None
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse JSON data for session {session_id}: {str(e)}"
                )
                status = "failed"
                result["error"] = f"Invalid summary data format: {str(e)}"
            except Exception as e:
                logger.error(
                    f"Unexpected error parsing summary data for {session_id}: {str(e)}"
                )
                status = "failed"
                result["error"] = f"Error processing summary data: {str(e)}"

        # Transform summary data into frontend format if available - PRESERVE ORDER
        transformed_data = {}
        if isinstance(summary_data, dict) and status == "completed":
            # Add SessionName / MeetingName to transformed data (support both for compat)
            transformed_data["SessionName"] = summary_data.get(
                "SessionName", summary_data.get("MeetingName", "")
            )
            transformed_data["MeetingName"] = transformed_data["SessionName"]

            # Map backend sections to frontend sections (currently empty mapping, using MeetingNotes)
            section_mapping = {}

            # Add each section to transformed data
            for backend_key, frontend_key in section_mapping.items():
                if backend_key in summary_data and isinstance(
                    summary_data[backend_key], dict
                ):
                    transformed_data[frontend_key] = summary_data[backend_key]

            # Add session/meeting notes sections if available - PRESERVE ORDER AND HANDLE DUPLICATES
            notes_data = summary_data.get("SessionNotes") or summary_data.get(
                "MeetingNotes"
            )
            if isinstance(notes_data, dict):
                sections_list = notes_data.get("sections", [])
                if isinstance(sections_list, list):
                    # Add section order array to maintain order
                    transformed_data["_section_order"] = []
                    used_keys = set()

                    for index, section in enumerate(sections_list):
                        if (
                            isinstance(section, dict)
                            and "title" in section
                            and "blocks" in section
                        ):
                            # Ensure blocks is a list to prevent frontend errors
                            if not isinstance(section.get("blocks"), list):
                                section["blocks"] = []

                            # Convert title to snake_case key
                            base_key = (
                                section["title"]
                                .lower()
                                .replace(" & ", "_")
                                .replace(" ", "_")
                            )

                            # Handle duplicate section names by adding index
                            key = base_key
                            if key in used_keys:
                                key = f"{base_key}_{index}"

                            used_keys.add(key)
                            transformed_data[key] = section
                            # Only add to _section_order if the section was successfully added
                            transformed_data["_section_order"].append(key)

        # Build response with both old and new field names for backward compat
        session_name = (
            summary_data.get("SessionName", summary_data.get("MeetingName"))
            if isinstance(summary_data, dict)
            else None
        )
        response = {
            "status": "processing"
            if status in ["processing", "pending", "started"]
            else status,
            "sessionName": session_name,
            "meetingName": session_name,
            "session_id": session_id,
            "meeting_id": session_id,
            "start": result.get("start_time"),
            "end": result.get("end_time"),
            "data": transformed_data if status == "completed" else None,
        }

        if status == "failed":
            response["status"] = "error"
            response["error"] = result.get("error", "Unknown processing error")
            response["data"] = None
            response["sessionName"] = None
            response["meetingName"] = None
            logger.info(f"Returning failed status with error: {response['error']}")
            return JSONResponse(status_code=400, content=response)

        elif status in ["processing", "pending", "started"]:
            response["data"] = None
            return JSONResponse(status_code=202, content=response)

        elif status == "completed":
            if not summary_data:
                response["status"] = "error"
                response["error"] = "Completed but summary data is missing or invalid"
                response["data"] = None
                response["sessionName"] = None
                response["meetingName"] = None
                return JSONResponse(status_code=500, content=response)
            return JSONResponse(status_code=200, content=response)

        else:
            response["status"] = "error"
            response["error"] = f"Unknown or unexpected status: {status}"
            response["data"] = None
            response["sessionName"] = None
            response["meetingName"] = None
            return JSONResponse(status_code=500, content=response)

    except Exception as e:
        logger.error(f"Error getting summary for {session_id}: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "sessionName": None,
                "meetingName": None,
                "session_id": session_id,
                "meeting_id": session_id,
                "data": None,
                "start": None,
                "end": None,
                "error": f"Internal server error: {str(e)}",
            },
        )


@app.post("/save-transcript")
async def save_transcript(request: SaveTranscriptRequest):
    """Save transcript segments for a session without processing"""
    try:
        logger.info(
            f"Received save-transcript request for session: {request.session_title}"
        )
        logger.info(f"Number of transcripts to save: {len(request.transcripts)}")

        # Log first transcript timestamps for debugging
        if request.transcripts:
            first = request.transcripts[0]
            logger.debug(
                f"First transcript: audio_start_time={first.audio_start_time}, audio_end_time={first.audio_end_time}, duration={first.duration}"
            )

        # Generate a unique session ID
        session_id = f"session-{int(time.time() * 1000)}"

        # Save the session with folder path (if provided)
        await db.save_session(
            session_id, request.session_title, folder_path=request.folder_path
        )

        # Save each transcript segment with timestamp fields for playback sync
        for transcript in request.transcripts:
            await db.save_session_transcript(
                session_id=session_id,
                transcript=transcript.text,
                timestamp=transcript.timestamp,
                summary="",
                action_items="",
                key_points="",
                audio_start_time=transcript.audio_start_time,
                audio_end_time=transcript.audio_end_time,
                duration=transcript.duration,
            )

        logger.info("Transcripts saved successfully")
        return {
            "status": "success",
            "message": "Transcript saved successfully",
            "session_id": session_id,
            "meeting_id": session_id,
        }
    except Exception as e:
        logger.error(f"Error saving transcript: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/get-model-config")
async def get_model_config():
    """Get the current model configuration"""
    model_config = await db.get_model_config()
    if model_config:
        api_key = await db.get_api_key(model_config["provider"])
        if api_key != None:
            model_config["apiKey"] = api_key
    return model_config


@app.post("/save-model-config")
async def save_model_config(request: SaveModelConfigRequest):
    """Save the model configuration"""
    await db.save_model_config(request.provider, request.model, request.whisperModel)
    if request.apiKey != None:
        await db.save_api_key(request.apiKey, request.provider)
    return {"status": "success", "message": "Model configuration saved successfully"}


@app.get("/get-transcript-config")
async def get_transcript_config():
    """Get the current transcript configuration"""
    transcript_config = await db.get_transcript_config()
    if transcript_config:
        transcript_api_key = await db.get_transcript_api_key(
            transcript_config["provider"]
        )
        if transcript_api_key != None:
            transcript_config["apiKey"] = transcript_api_key
    return transcript_config


@app.post("/save-transcript-config")
async def save_transcript_config(request: SaveTranscriptConfigRequest):
    """Save the transcript configuration"""
    await db.save_transcript_config(request.provider, request.model)
    if request.apiKey != None:
        await db.save_transcript_api_key(request.apiKey, request.provider)
    return {
        "status": "success",
        "message": "Transcript configuration saved successfully",
    }


class GetApiKeyRequest(BaseModel):
    provider: str


@app.post("/get-api-key")
async def get_api_key(request: GetApiKeyRequest):
    try:
        return await db.get_api_key(request.provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/get-transcript-api-key")
async def get_transcript_api_key(request: GetApiKeyRequest):
    try:
        return await db.get_transcript_api_key(request.provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


class SessionSummaryUpdate(BaseModel):
    session_id: str
    summary: dict


# Keep old field name compat alias
class MeetingSummaryUpdate(BaseModel):
    meeting_id: str
    summary: dict


@app.post("/save-session-summary")
async def save_session_summary(data: SessionSummaryUpdate):
    """Save a session summary"""
    try:
        await db.update_session_summary(data.session_id, data.summary)
        return {"message": "Session summary saved successfully"}
    except ValueError as ve:
        logger.error(f"Value error saving session summary: {str(ve)}")
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Error saving session summary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


class SearchRequest(BaseModel):
    query: str


@app.post("/search-transcripts")
async def search_transcripts(request: SearchRequest):
    """Search through session transcripts for the given query"""
    try:
        results = await db.search_transcripts(request.query)
        return JSONResponse(content=results)
    except Exception as e:
        logger.error(f"Error searching transcripts: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on API shutdown"""
    logger.info("API shutting down, cleaning up resources")
    try:
        processor.cleanup()
        await db.close()
        logger.info("Successfully cleaned up resources")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}", exc_info=True)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5167"))
    reload = os.environ.get("RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host=host, port=port, reload=reload)
