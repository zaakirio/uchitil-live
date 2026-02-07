import logging

logger = logging.getLogger(__name__)


class SchemaValidator:
    """No-op schema validator for MongoDB-backed Uchitil Live.

    MongoDB is schemaless, so traditional schema validation is not needed.
    This class is kept as a no-op stub for backward compatibility with any
    code that may still reference it.
    """

    def __init__(self, *args, **kwargs):
        pass

    def validate_schema(self):
        """No-op: MongoDB collections do not require schema validation."""
        logger.info("SchemaValidator.validate_schema() called — no-op for MongoDB")
        return True
