import asyncio
import json
import os
from datetime import datetime
from typing import Optional, Dict, List
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import TEXT

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


class DatabaseManager:
    """Async MongoDB database manager for Uchitil Live sessions."""

    def __init__(self):
        self.uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.db_name = os.getenv("MONGODB_DATABASE", "uchitil-live")
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None

    async def initialize(self):
        """Initialize MongoDB connection with retry logic and create indexes."""
        safe_uri = self.uri.split("@")[-1] if "@" in self.uri else self.uri

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    f"Connecting to MongoDB at ...@{safe_uri} (database: {self.db_name}) [attempt {attempt}/{MAX_RETRIES}]"
                )
                self.client = AsyncIOMotorClient(
                    self.uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    maxPoolSize=10,
                    minPoolSize=1,
                    retryWrites=True,
                    retryReads=True,
                )
                self.db = self.client[self.db_name]

                # Verify the connection
                await self.client.admin.command("ping")
                logger.info("Successfully connected to MongoDB")

                # Create text indexes for search functionality
                await self.db.transcripts.create_index(
                    [("transcript", TEXT)], background=True
                )
                await self.db.transcript_chunks.create_index(
                    [("transcript_text", TEXT)], background=True
                )

                # Create indexes for common lookups
                await self.db.transcripts.create_index("session_id", background=True)
                await self.db.summary_processes.create_index(
                    "session_id", background=True
                )
                await self.db.transcript_chunks.create_index(
                    "session_id", background=True
                )

                logger.info("Database indexes created successfully")
                return  # Success — exit retry loop
            except Exception as e:
                logger.error(
                    f"Database initialization attempt {attempt} failed: {str(e)}"
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_SECONDS * attempt
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("All database connection attempts exhausted")
                    raise

    async def close(self):
        """Close the MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

    # ─── Session CRUD ────────────────────────────────────────────────

    async def save_session(self, session_id: str, title: str, folder_path: str = None):
        """Save or create a new session."""
        try:
            existing = await self.db.sessions.find_one(
                {"$or": [{"_id": session_id}, {"title": title}]}
            )
            if existing:
                raise Exception(f"Session with ID {session_id} already exists")

            now = datetime.utcnow().isoformat()
            doc = {
                "_id": session_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "folder_path": folder_path,
            }
            await self.db.sessions.insert_one(doc)
            logger.info(f"Saved session {session_id} with folder_path: {folder_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving session: {str(e)}")
            raise

    async def get_session(self, session_id: str):
        """Get a session by ID with all its transcripts."""
        try:
            session = await self.db.sessions.find_one({"_id": session_id})
            if not session:
                return None

            transcripts_cursor = self.db.transcripts.find({"session_id": session_id})
            transcripts = await transcripts_cursor.to_list(length=None)

            return {
                "id": session["_id"],
                "title": session["title"],
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "transcripts": [
                    {
                        "id": session_id,
                        "text": t.get("transcript", ""),
                        "timestamp": t.get("timestamp", ""),
                        "audio_start_time": t.get("audio_start_time"),
                        "audio_end_time": t.get("audio_end_time"),
                        "duration": t.get("duration"),
                    }
                    for t in transcripts
                ],
            }
        except Exception as e:
            logger.error(f"Error getting session: {str(e)}")
            raise

    async def get_all_sessions(self):
        """Get all sessions with basic information."""
        cursor = self.db.sessions.find(
            {}, {"_id": 1, "title": 1, "created_at": 1}
        ).sort("created_at", -1)
        rows = await cursor.to_list(length=None)
        return [
            {"id": r["_id"], "title": r["title"], "created_at": r.get("created_at", "")}
            for r in rows
        ]

    async def delete_session(self, session_id: str):
        """Delete a session and all its associated data."""
        if not session_id or not session_id.strip():
            raise ValueError("session_id cannot be empty")

        try:
            session = await self.db.sessions.find_one({"_id": session_id})
            if not session:
                logger.warning(f"Session {session_id} not found for deletion")
                return False

            # Delete all related documents
            await self.db.transcript_chunks.delete_many({"session_id": session_id})
            await self.db.summary_processes.delete_many({"session_id": session_id})
            await self.db.transcripts.delete_many({"session_id": session_id})
            result = await self.db.sessions.delete_one({"_id": session_id})

            if result.deleted_count == 0:
                logger.error(
                    f"Failed to delete session {session_id} - no rows affected"
                )
                return False

            logger.info(
                f"Successfully deleted session {session_id} and all associated data"
            )
            return True
        except Exception as e:
            logger.error(
                f"Error deleting session {session_id}: {str(e)}", exc_info=True
            )
            return False

    async def update_session_name(self, session_id: str, name: str):
        """Update session name in both sessions and transcript_chunks collections."""
        now = datetime.utcnow().isoformat()
        await self.db.sessions.update_one(
            {"_id": session_id},
            {"$set": {"title": name, "updated_at": now}},
        )
        await self.db.transcript_chunks.update_many(
            {"session_id": session_id},
            {"$set": {"session_name": name}},
        )

    async def update_session_title(self, session_id: str, new_title: str):
        """Update a session's title."""
        now = datetime.utcnow().isoformat()
        await self.db.sessions.update_one(
            {"_id": session_id},
            {"$set": {"title": new_title, "updated_at": now}},
        )

    # ─── Transcript Operations ───────────────────────────────────────

    async def save_session_transcript(
        self,
        session_id: str,
        transcript: str,
        timestamp: str,
        summary: str = "",
        action_items: str = "",
        key_points: str = "",
        audio_start_time: float = None,
        audio_end_time: float = None,
        duration: float = None,
    ):
        """Save a transcript segment for a session with optional recording-relative timestamps."""
        try:
            doc = {
                "session_id": session_id,
                "transcript": transcript,
                "timestamp": timestamp,
                "summary": summary,
                "action_items": action_items,
                "key_points": key_points,
                "audio_start_time": audio_start_time,
                "audio_end_time": audio_end_time,
                "duration": duration,
            }
            await self.db.transcripts.insert_one(doc)
            return True
        except Exception as e:
            logger.error(f"Error saving transcript: {str(e)}")
            raise

    async def save_transcript(
        self,
        session_id: str,
        transcript_text: str,
        model: str,
        model_name: str,
        chunk_size: int,
        overlap: int,
    ):
        """Save transcript data (full transcript chunk for processing)."""
        if not session_id or not session_id.strip():
            raise ValueError("session_id cannot be empty")
        if not transcript_text or not transcript_text.strip():
            raise ValueError("transcript_text cannot be empty")
        if chunk_size <= 0 or overlap < 0:
            raise ValueError("Invalid chunk_size or overlap values")
        if len(transcript_text) > 10_000_000:
            raise ValueError("Transcript text too large (>10MB)")

        now = datetime.utcnow().isoformat()

        try:
            await self.db.transcript_chunks.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "session_id": session_id,
                        "transcript_text": transcript_text,
                        "model": model,
                        "model_name": model_name,
                        "chunk_size": chunk_size,
                        "overlap": overlap,
                        "created_at": now,
                    }
                },
                upsert=True,
            )
            logger.info(
                f"Successfully saved transcript for session_id: {session_id} (size: {len(transcript_text)} chars)"
            )
        except Exception as e:
            logger.error(
                f"Failed to save transcript for session_id {session_id}: {str(e)}",
                exc_info=True,
            )
            raise

    async def get_transcript(self, session_id: str):
        """Get transcript data for a session (alias for get_transcript_data)."""
        return await self.get_transcript_data(session_id)

    async def get_transcript_data(self, session_id: str):
        """Get transcript data for a session by joining transcript_chunks and summary_processes."""
        chunk = await self.db.transcript_chunks.find_one({"session_id": session_id})
        process = await self.db.summary_processes.find_one({"session_id": session_id})

        if not chunk and not process:
            return None

        result = {}
        if chunk:
            result.update(
                {
                    "session_id": chunk.get("session_id"),
                    "session_name": chunk.get("session_name"),
                    "transcript_text": chunk.get("transcript_text"),
                    "model": chunk.get("model"),
                    "model_name": chunk.get("model_name"),
                    "chunk_size": chunk.get("chunk_size"),
                    "overlap": chunk.get("overlap"),
                    "created_at": chunk.get("created_at"),
                }
            )
        if process:
            result.update(
                {
                    "status": process.get("status"),
                    "result": process.get("result"),
                    "error": process.get("error"),
                    "start_time": process.get("start_time"),
                    "end_time": process.get("end_time"),
                    "chunk_count": process.get("chunk_count"),
                    "processing_time": process.get("processing_time"),
                    "metadata": process.get("metadata"),
                }
            )

        return result if result else None

    # ─── Process Operations ──────────────────────────────────────────

    async def create_process(self, session_id: str) -> str:
        """Create a new process entry or update existing one and return its ID."""
        now = datetime.utcnow().isoformat()

        try:
            result = await self.db.summary_processes.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "status": "PENDING",
                        "updated_at": now,
                        "start_time": now,
                        "error": None,
                        "result": None,
                    },
                    "$setOnInsert": {
                        "session_id": session_id,
                        "created_at": now,
                    },
                },
                upsert=True,
            )
            logger.info(
                f"Successfully created/updated process for session_id: {session_id}"
            )
            return session_id
        except Exception as e:
            logger.error(
                f"Failed to create process for session_id {session_id}: {str(e)}",
                exc_info=True,
            )
            raise

    async def update_process(
        self,
        session_id: str,
        status: str,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        chunk_count: Optional[int] = None,
        processing_time: Optional[float] = None,
        metadata: Optional[Dict] = None,
    ):
        """Update a process status and result."""
        now = datetime.utcnow().isoformat()

        try:
            update_fields = {"status": status, "updated_at": now}

            if result is not None:
                # If result is a string (already JSON-serialised), store as-is
                if isinstance(result, str):
                    update_fields["result"] = result
                else:
                    try:
                        update_fields["result"] = json.dumps(result)
                    except (TypeError, ValueError) as e:
                        logger.error(
                            f"Failed to serialize result for session_id {session_id}: {str(e)}"
                        )
                        raise ValueError("Result data cannot be JSON serialized")

            if error:
                sanitized_error = str(error).replace("\n", " ").replace("\r", "")[:1000]
                update_fields["error"] = sanitized_error

            if chunk_count is not None:
                update_fields["chunk_count"] = chunk_count

            if processing_time is not None:
                update_fields["processing_time"] = processing_time

            if metadata is not None:
                try:
                    update_fields["metadata"] = json.dumps(metadata)
                except (TypeError, ValueError) as e:
                    logger.error(
                        f"Failed to serialize metadata for session_id {session_id}: {str(e)}"
                    )

            if status.upper() in ["COMPLETED", "FAILED"]:
                update_fields["end_time"] = now

            update_result = await self.db.summary_processes.update_one(
                {"session_id": session_id},
                {"$set": update_fields},
            )

            if update_result.matched_count == 0:
                logger.warning(
                    f"No process found to update for session_id: {session_id}"
                )

            logger.debug(
                f"Successfully updated process status to {status} for session_id: {session_id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to update process for session_id {session_id}: {str(e)}",
                exc_info=True,
            )
            raise

    async def get_process(self, session_id: str):
        """Get the process document for a session."""
        doc = await self.db.summary_processes.find_one({"session_id": session_id})
        if not doc:
            return None
        # Remove MongoDB _id for serialization
        doc.pop("_id", None)
        return doc

    # ─── Summary Operations ──────────────────────────────────────────

    async def update_session_summary(self, session_id: str, summary: dict):
        """Update a session's summary."""
        now = datetime.utcnow().isoformat()
        try:
            session = await self.db.sessions.find_one({"_id": session_id})
            if not session:
                raise ValueError(f"Session with ID {session_id} not found")

            await self.db.summary_processes.update_one(
                {"session_id": session_id},
                {"$set": {"result": json.dumps(summary), "updated_at": now}},
                upsert=True,
            )
            await self.db.sessions.update_one(
                {"_id": session_id},
                {"$set": {"updated_at": now}},
            )
            return True
        except Exception as e:
            logger.error(f"Error updating session summary: {str(e)}")
            raise

    # ─── Model Config / Settings ─────────────────────────────────────

    async def get_model_config(self):
        """Get the current model configuration."""
        doc = await self.db.settings.find_one({"_id": "1"})
        if not doc:
            return None
        return {
            "provider": doc.get("provider"),
            "model": doc.get("model"),
            "whisperModel": doc.get("whisperModel"),
        }

    async def save_model_config(self, provider: str, model: str, whisperModel: str):
        """Save the model configuration."""
        if not provider or not provider.strip():
            raise ValueError("Provider cannot be empty")
        if not model or not model.strip():
            raise ValueError("Model cannot be empty")
        if not whisperModel or not whisperModel.strip():
            raise ValueError("Whisper model cannot be empty")

        try:
            await self.db.settings.update_one(
                {"_id": "1"},
                {
                    "$set": {
                        "provider": provider,
                        "model": model,
                        "whisperModel": whisperModel,
                    }
                },
                upsert=True,
            )
            logger.info(f"Successfully saved model configuration: {provider}/{model}")
        except Exception as e:
            logger.error(f"Failed to save model configuration: {str(e)}", exc_info=True)
            raise

    async def save_api_key(self, api_key: str, provider: str):
        """Save the API key for a provider."""
        provider_key_map = {
            "openai": "openaiApiKey",
            "claude": "anthropicApiKey",
            "groq": "groqApiKey",
            "ollama": "ollamaApiKey",
        }
        if provider not in provider_key_map:
            raise ValueError(f"Invalid provider: {provider}")

        api_key_name = provider_key_map[provider]

        try:
            await self.db.settings.update_one(
                {"_id": "1"},
                {
                    "$set": {api_key_name: api_key},
                    "$setOnInsert": {
                        "provider": "openai",
                        "model": "gpt-4o-2024-11-20",
                        "whisperModel": "large-v3",
                    },
                },
                upsert=True,
            )
            logger.info(f"Successfully saved API key for provider: {provider}")
        except Exception as e:
            logger.error(
                f"Failed to save API key for provider {provider}: {str(e)}",
                exc_info=True,
            )
            raise

    async def get_api_key(self, provider: str):
        """Get the API key for a provider."""
        provider_key_map = {
            "openai": "openaiApiKey",
            "claude": "anthropicApiKey",
            "groq": "groqApiKey",
            "ollama": "ollamaApiKey",
        }
        if provider not in provider_key_map:
            raise ValueError(f"Invalid provider: {provider}")

        api_key_name = provider_key_map[provider]
        doc = await self.db.settings.find_one({"_id": "1"})
        if doc and doc.get(api_key_name):
            return doc[api_key_name]
        return ""

    async def delete_api_key(self, provider: str):
        """Delete the API key for a provider."""
        provider_key_map = {
            "openai": "openaiApiKey",
            "claude": "anthropicApiKey",
            "groq": "groqApiKey",
            "ollama": "ollamaApiKey",
        }
        if provider not in provider_key_map:
            raise ValueError(f"Invalid provider: {provider}")

        api_key_name = provider_key_map[provider]
        await self.db.settings.update_one(
            {"_id": "1"},
            {"$unset": {api_key_name: ""}},
        )

    # ─── Transcript Config / Settings ────────────────────────────────

    async def get_transcript_config(self):
        """Get the current transcript configuration."""
        doc = await self.db.transcript_settings.find_one({"_id": "1"})
        if doc:
            return {"provider": doc.get("provider"), "model": doc.get("model")}
        return {"provider": "localWhisper", "model": "large-v3"}

    async def save_transcript_config(self, provider: str, model: str):
        """Save the transcript settings."""
        if not provider or not provider.strip():
            raise ValueError("Provider cannot be empty")
        if not model or not model.strip():
            raise ValueError("Model cannot be empty")

        try:
            await self.db.transcript_settings.update_one(
                {"_id": "1"},
                {"$set": {"provider": provider, "model": model}},
                upsert=True,
            )
            logger.info(
                f"Successfully saved transcript configuration: {provider}/{model}"
            )
        except Exception as e:
            logger.error(
                f"Failed to save transcript configuration: {str(e)}", exc_info=True
            )
            raise

    async def save_transcript_api_key(self, api_key: str, provider: str):
        """Save the transcript API key."""
        provider_key_map = {
            "localWhisper": "whisperApiKey",
            "deepgram": "deepgramApiKey",
            "elevenLabs": "elevenLabsApiKey",
            "groq": "groqApiKey",
            "openai": "openaiApiKey",
        }
        if provider not in provider_key_map:
            raise ValueError(f"Invalid provider: {provider}")

        api_key_name = provider_key_map[provider]

        try:
            await self.db.transcript_settings.update_one(
                {"_id": "1"},
                {
                    "$set": {api_key_name: api_key},
                    "$setOnInsert": {
                        "provider": "localWhisper",
                        "model": "large-v3",
                    },
                },
                upsert=True,
            )
            logger.info(
                f"Successfully saved transcript API key for provider: {provider}"
            )
        except Exception as e:
            logger.error(
                f"Failed to save transcript API key for provider {provider}: {str(e)}",
                exc_info=True,
            )
            raise

    async def get_transcript_api_key(self, provider: str):
        """Get the transcript API key."""
        provider_key_map = {
            "localWhisper": "whisperApiKey",
            "deepgram": "deepgramApiKey",
            "elevenLabs": "elevenLabsApiKey",
            "groq": "groqApiKey",
            "openai": "openaiApiKey",
        }
        if provider not in provider_key_map:
            raise ValueError(f"Invalid provider: {provider}")

        api_key_name = provider_key_map[provider]
        doc = await self.db.transcript_settings.find_one({"_id": "1"})
        if doc and doc.get(api_key_name):
            return doc[api_key_name]
        return ""

    # ─── Search ──────────────────────────────────────────────────────

    async def search_transcripts(self, query: str):
        """Search through session transcripts using MongoDB text search."""
        if not query or query.strip() == "":
            return []

        try:
            results = []
            seen_session_ids = set()

            # Search in transcripts collection using text index
            cursor = self.db.transcripts.find(
                {"$text": {"$search": query}},
                {"score": {"$meta": "textScore"}},
            ).sort([("score", {"$meta": "textScore"})])

            async for doc in cursor:
                session_id = doc.get("session_id")
                session = await self.db.sessions.find_one({"_id": session_id})
                if not session:
                    continue

                transcript_text = doc.get("transcript", "")
                transcript_lower = transcript_text.lower()
                match_index = transcript_lower.find(query.lower())

                if match_index >= 0:
                    start_index = max(0, match_index - 100)
                    end_index = min(
                        len(transcript_text), match_index + len(query) + 100
                    )
                    context = transcript_text[start_index:end_index]
                    if start_index > 0:
                        context = "..." + context
                    if end_index < len(transcript_text):
                        context += "..."
                else:
                    context = transcript_text[:200] + (
                        "..." if len(transcript_text) > 200 else ""
                    )

                seen_session_ids.add(session_id)
                results.append(
                    {
                        "id": session_id,
                        "title": session.get("title", ""),
                        "matchContext": context,
                        "timestamp": doc.get(
                            "timestamp", datetime.utcnow().isoformat()
                        ),
                    }
                )

            # Also search in transcript_chunks collection
            chunk_cursor = self.db.transcript_chunks.find(
                {"$text": {"$search": query}},
                {"score": {"$meta": "textScore"}},
            ).sort([("score", {"$meta": "textScore"})])

            async for doc in chunk_cursor:
                session_id = doc.get("session_id")
                if session_id in seen_session_ids:
                    continue

                session = await self.db.sessions.find_one({"_id": session_id})
                if not session:
                    continue

                transcript_text = doc.get("transcript_text", "")
                transcript_lower = transcript_text.lower()
                match_index = transcript_lower.find(query.lower())

                if match_index >= 0:
                    start_index = max(0, match_index - 100)
                    end_index = min(
                        len(transcript_text), match_index + len(query) + 100
                    )
                    context = transcript_text[start_index:end_index]
                    if start_index > 0:
                        context = "..." + context
                    if end_index < len(transcript_text):
                        context += "..."
                else:
                    context = transcript_text[:200] + (
                        "..." if len(transcript_text) > 200 else ""
                    )

                results.append(
                    {
                        "id": session_id,
                        "title": session.get("title", ""),
                        "matchContext": context,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )

            return results

        except Exception as e:
            logger.error(f"Error searching transcripts: {str(e)}")
            raise
